import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import admin, agents, alerts, audit, auth, dashboard, install, labs, machines, notifications, updates
from app.config import get_settings
from app.db import get_session_factory, init_models
from app.services.alerts import seed_default_rules
from app.services.heartbeat import reconcile_machine_status
from app.services.retention import rollup_and_prune

logger = logging.getLogger("labwatch")


async def seed() -> None:
    from sqlalchemy import func, select

    from app.config import get_settings
    from app.enums import NotificationChannel, UserRole
    from app.models import Lab, NotificationChannelConfig, RegistrationToken, User
    from app.security import hash_password, hash_token, new_secret

    settings = get_settings()
    async with get_session_factory()() as db:
        users = (await db.execute(select(User))).scalars().first()
        if not users:
            db.add(
                User(
                    username=settings.admin_username,
                    email=settings.admin_email,
                    password_hash=hash_password(settings.admin_password),
                    full_name="Administrator",
                    role=UserRole.ADMIN.value,
                )
            )
            logger.warning("Created bootstrap admin user '%s'", settings.admin_username)
        unassigned = (
            await db.execute(select(Lab).where(func.lower(Lab.name) == "unassigned"))
        ).scalar_one_or_none()
        if not unassigned:
            db.add(Lab(name="Unassigned", description="Default lab for newly registered machines"))
        await seed_default_rules(db)
        for channel in NotificationChannel:
            existing = (
                await db.execute(select(NotificationChannelConfig).where(NotificationChannelConfig.channel == channel.value))
            ).scalar_one_or_none()
            if not existing:
                db.add(
                    NotificationChannelConfig(
                        channel=channel.value,
                        enabled=channel.value == NotificationChannel.DASHBOARD.value,
                        config={},
                    )
                )
        token_exists = (await db.execute(select(RegistrationToken))).scalars().first()
        if not token_exists:
            raw = "lw_dev_" + new_secret(16)
            db.add(
                RegistrationToken(
                    token_hash=hash_token(raw),
                    token_prefix=raw[:10],
                    label="bootstrap-dev",
                )
            )
            logger.warning(
                "Created bootstrap registration token prefix=%s. The plaintext is only logged outside production.",
                raw[:10],
            )
            if settings.env != "production":
                logger.warning("Bootstrap registration token (dev): %s", raw)
        await db.commit()


async def _loop(name: str, interval: float, coro_factory):
    while True:
        try:
            async with get_session_factory()() as db:
                await coro_factory(db)
                await db.commit()
        except Exception:
            logger.exception("Background task %s failed", name)
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    last_error: Exception | None = None
    for attempt in range(1, 16):
        try:
            await init_models()
            await seed()
            last_error = None
            break
        except Exception as exc:
            last_error = exc
            logger.exception("API startup failed (attempt %s/15)", attempt)
            await asyncio.sleep(2)
    if last_error is not None:
        raise last_error
    tasks = [
        asyncio.create_task(_loop("heartbeat", 15, reconcile_machine_status)),
        asyncio.create_task(_loop("retention", 3600, rollup_and_prune)),
    ]
    yield
    for t in tasks:
        t.cancel()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="LabWatch API",
        description="Lab Hardware Monitoring & Asset Management System",
        version=__version__,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for r in (auth, agents, machines, labs, alerts, admin, dashboard, notifications, audit, updates, install):
        app.include_router(r.router)

    @app.get("/health")
    async def health():
        from sqlalchemy import text

        from app.db import get_engine, lab_column_names

        payload = {"status": "ok", "version": __version__, "database": "down", "labs_ok": False}
        try:
            engine = get_engine()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                payload["database"] = "ok"
                cols = await conn.run_sync(lab_column_names)
                needed = [
                    "name",
                    "building",
                    "room",
                    "code",
                    "department",
                    "floor",
                    "capacity",
                    "incharge",
                    "phone",
                    "email",
                    "description",
                ]
                missing = [name for name in needed if name not in cols]
                payload["lab_columns"] = cols
                payload["lab_missing_columns"] = missing
                payload["labs_ok"] = not missing
        except Exception as exc:
            payload["database"] = f"{type(exc).__name__}: {exc}"
        return payload

    return app


app = create_app()
