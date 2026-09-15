import os

os.environ.setdefault("LABWATCH_SECRET_KEY", "test-secret-key-for-labwatch-tests")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "testpass123")
os.environ.setdefault("ADMIN_EMAIL", "admin@test.local")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base, get_db, reset_engine
from app.main import create_app
from app import models  # noqa: F401


@pytest.fixture
async def db_session(tmp_path, monkeypatch):
    db_path = tmp_path / "unit.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    reset_engine()
    engine = create_async_engine(url, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()
    reset_engine()


@pytest.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "api.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("LABWATCH_SECRET_KEY", "test-secret-key-for-labwatch-tests")
    monkeypatch.setenv("ADMIN_PASSWORD", "testpass123")
    reset_engine()
    app = create_app()
    from app.db import get_engine, init_models
    from app.main import seed

    await init_models()
    await seed()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    engine = get_engine()
    await engine.dispose()
    reset_engine()


@pytest.fixture
async def auth_headers(client: AsyncClient):
    r = await client.post("/api/auth/login", json={"username": "admin", "password": "testpass123"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
