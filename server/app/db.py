from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


def json_column():
    return JSON().with_variant(JSONB(), "postgresql")


class TZDateTime(TypeDecorator):
    """Store UTC naive timestamps; return timezone-aware UTC datetimes.

    PostgreSQL TIMESTAMP WITHOUT TIME ZONE (asyncpg) rejects aware datetimes.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
SessionLocal: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, SessionLocal
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=not settings.is_sqlite,
            connect_args={"check_same_thread": False} if settings.is_sqlite else {},
        )
        SessionLocal = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert SessionLocal is not None
    return SessionLocal


def reset_engine() -> None:
    global _engine, SessionLocal
    _engine = None
    SessionLocal = None
    get_settings.cache_clear()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def init_models() -> None:
    from app import models  # noqa: F401

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_machine_address_columns)
        await conn.run_sync(ensure_lab_columns)


def machine_address_column_sql(dialect_name: str) -> dict[str, str]:
    if dialect_name == "postgresql":
        return {
            "current_ips": "JSONB",
            "previous_ip": "VARCHAR(64)",
            "ip_changed_at": "TIMESTAMPTZ",
        }
    return {
        "current_ips": "JSON",
        "previous_ip": "VARCHAR(64)",
        "ip_changed_at": "DATETIME",
    }


def _ensure_machine_address_columns(sync_conn) -> None:
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if "machines" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("machines")}
    for name, sql_type in machine_address_column_sql(sync_conn.dialect.name).items():
        if name not in existing:
            sync_conn.execute(text(f"ALTER TABLE machines ADD COLUMN {name} {sql_type}"))


def ensure_lab_columns(sync_conn) -> None:
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if "labs" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("labs")}
    columns = (
        ("building", "VARCHAR(120) DEFAULT ''"),
        ("room", "VARCHAR(64) DEFAULT ''"),
        ("code", "VARCHAR(32) DEFAULT ''"),
        ("department", "VARCHAR(120) DEFAULT ''"),
        ("floor", "VARCHAR(32) DEFAULT ''"),
        ("capacity", "INTEGER DEFAULT 0"),
        ("incharge", "VARCHAR(120) DEFAULT ''"),
        ("phone", "VARCHAR(64) DEFAULT ''"),
        ("email", "VARCHAR(255) DEFAULT ''"),
    )
    for name, sql_type in columns:
        if name not in existing:
            sync_conn.execute(text(f"ALTER TABLE labs ADD COLUMN {name} {sql_type}"))


def lab_column_names(sync_conn) -> list[str]:
    from sqlalchemy import inspect

    insp = inspect(sync_conn)
    if "labs" not in insp.get_table_names():
        return []
    return [c["name"] for c in insp.get_columns("labs")]
