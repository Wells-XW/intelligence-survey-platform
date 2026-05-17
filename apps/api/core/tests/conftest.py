"""Shared test fixtures for the Intelligence Survey Platform API."""

# Force the test database URL to point at the live test Postgres on
# port 5433 BEFORE app.config is imported. The default settings value
# targets port 5432, which is not running in this environment.
import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://survey:survey@localhost:5433/survey_test_db",
)

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import app

# Use a separate test database (same server, different DB name)
TEST_DATABASE_URL = settings.database_url.replace("survey_db", "survey_test_db")


@pytest_asyncio.fixture
async def test_engine():
    """Create a fresh test database engine per test.

    Per-test scope is required because asyncpg connections are bound to
    the event loop on which they were created. pytest-asyncio 1.x runs
    each test on its own loop by default, so a session-scoped engine
    leaks asyncpg connections across loops and trips
    ``RuntimeError: ... attached to a different loop`` or
    ``InterfaceError: another operation is in progress``.
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine):
    """Provide a clean database session per test (rolls back after)."""
    async_session = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        async with session.begin() as transaction:
            yield session
            await transaction.rollback()


@pytest_asyncio.fixture(autouse=True)
async def _reset_app_loop_caches():
    """Reset module-level async clients pinned to the previous loop.

    The FastAPI ``app`` is constructed once at import time, so any
    middleware that lazily caches an asyncio resource (Redis client,
    DB engine) ends up bound to whichever event loop happened to make
    the first call. pytest-asyncio creates a fresh loop for each test
    by default, which makes those cached clients unusable on the
    next test and surfaces as
    ``RuntimeError: ... attached to a different loop`` (which then
    causes the rate-limit middleware to fail closed with 503 and mask
    the 401 the test is asserting on).

    Clearing the well-known caches before each test gives every test
    a clean slate without changing how production code behaves.
    """
    from app.middleware.rate_limit import RateLimitMiddleware

    # Walk the live middleware stack (built lazily on first request,
    # then cached on the app) and null out the rate-limit instance's
    # cached aioredis client.
    stack = getattr(app, "middleware_stack", None)
    node = stack
    seen = 0
    while node is not None and seen < 16:
        if isinstance(node, RateLimitMiddleware):
            node._redis = None
        node = getattr(node, "app", None)
        seen += 1

    # The app's main DB engine (used by the rate-limit middleware's
    # audit emission via ``app.database.async_session``) is also
    # loop-bound. Disposing it forces a fresh asyncpg pool on the
    # current loop.
    from app import database as app_db

    try:
        await app_db.engine.dispose()
    except Exception:
        pass

    yield


@pytest_asyncio.fixture
async def async_client(db_session):
    """HTTP test client with the test database session injected."""
    app.dependency_overrides[get_db] = lambda: db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_headers(async_client):
    """Register + login a test user, return Authorization headers."""
    email = "test@example.com"
    password = "Test1234!"
    display_name = "Test User"

    # Register
    await async_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": display_name},
    )

    # Login
    form = {"username": email, "password": password}
    resp = await async_client.post("/api/v1/auth/login", data=form)
    tokens = resp.json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}
