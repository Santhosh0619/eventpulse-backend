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


# Guard so the test database is created only once per test session.
_db_initialized = False


@pytest_asyncio.fixture
async def test_engine():
    """Function-scoped async engine bound to the test database.

    Function scope keeps the engine on the same event loop as the test that uses
    it (pytest-asyncio runs each test in its own loop). The database and tables
    are created once; per-test isolation comes from the savepoint rollback in
    ``db_session``.
    """
    global _db_initialized
    if not _db_initialized:
        await _ensure_test_database()
        _db_initialized = True

    engine = create_async_engine(TEST_DATABASE_URL)
    # ``create_all`` is idempotent (checkfirst=True), so this is cheap after the
    # first test once the schema already exists.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Function-scoped session wrapped in a transaction that is rolled back."""
    connection = await test_engine.connect()
    transaction = await connection.begin()
    # ``create_savepoint`` makes the session commit/rollback against a SAVEPOINT,
    # so application-level commits never end the outer transaction. The outer
    # rollback then discards everything, keeping each test fully isolated.
    session_factory = async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
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


@pytest_asyncio.fixture(autouse=True)
async def _reset_redis():
    """Reset the module-level Redis client and flush cached state around each test.

    The app caches a single Redis client, but pytest-asyncio gives every test its
    own event loop, so a client created in one test is unusable in the next.
    Resetting forces a fresh client bound to the current loop and closes it after.
    Flushing at setup keeps cache entries (e.g. event listings, which share keys
    across tests) from leaking between otherwise-isolated tests.
    """
    import app.core.redis as redis_mod

    redis_mod._redis = None
    await redis_mod.get_redis().flushdb()
    yield
    if redis_mod._redis is not None:
        await redis_mod._redis.aclose()
        redis_mod._redis = None


@pytest_asyncio.fixture(autouse=True)
def _disable_rate_limit():
    """Disable rate limiting for the general suite.

    Most tests fire many requests from one client (a single IP/identity) and would
    otherwise trip the limiter. The dedicated rate-limit test re-enables it.
    """
    from app.core.rate_limit import limiter

    limiter.enabled = False
    yield
    limiter.enabled = True


# ---------------------------------------------------------------------------
# Data helpers / fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def make_user(db_session: AsyncSession):
    """Return a factory coroutine that persists a ``User`` (+ profile) for tests."""
    from app.core.security import hash_password
    from app.features.users.models import User, UserProfile

    _counter = {"n": 0}

    async def _make(
        *,
        email: str | None = None,
        password: str = "Password123!",
        first_name: str = "Test",
        last_name: str = "User",
        role: str = "attendee",
        is_verified: bool = True,
        is_active: bool = True,
    ) -> User:
        _counter["n"] += 1
        if email is None:
            email = f"user{_counter['n']}@example.com"
        user = User(
            email=email,
            password_hash=hash_password(password),
            role=role,
            is_verified=is_verified,
            is_active=is_active,
            profile=UserProfile(first_name=first_name, last_name=last_name),
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        return user

    return _make


@pytest_asyncio.fixture
async def verified_user(make_user):
    """A verified, active attendee user."""
    return await make_user()


@pytest_asyncio.fixture
def auth_headers():
    """Return a helper building an Authorization header for a given user."""
    from app.core.security import create_access_token

    def _headers(user) -> dict[str, str]:
        token = create_access_token(str(user.id), extra_claims={"role": user.role})
        return {"Authorization": f"Bearer {token}"}

    return _headers
