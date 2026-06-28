"""Pytest fixtures: isolated test database, async session, and HTTP client.

A dedicated ``eventpulse_test`` database is created once per test session. Each
test runs inside a transaction that is rolled back afterwards, so tests never
share state and stay independent.
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.core.database import Base
from app.core.dependencies import get_db
from app.main import app

# Derive a separate test database URL from the configured DATABASE_URL.
_TEST_DB_NAME = "eventpulse_test"
_base_url, _orig_db = settings.DATABASE_URL.rsplit("/", 1)
TEST_DATABASE_URL = f"{_base_url}/{_TEST_DB_NAME}"
MAINTENANCE_URL = f"{_base_url}/postgres"


async def _ensure_test_database() -> None:
    """Create the test database if it does not already exist."""
    from sqlalchemy import text

    engine = create_async_engine(MAINTENANCE_URL, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": _TEST_DB_NAME},
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{_TEST_DB_NAME}"'))
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Session-scoped async engine bound to the test database with all tables."""
    await _ensure_test_database()
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=None)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Function-scoped session wrapped in a transaction that is rolled back."""
    connection = await test_engine.connect()
    transaction = await connection.begin()
    session_factory = async_sessionmaker(bind=connection, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client with the database dependency overridden to the test session."""

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
