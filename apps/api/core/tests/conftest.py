"""Shared test fixtures for the Intelligence Survey Platform API."""

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import app

# Use a separate test database (same server, different DB name)
TEST_DATABASE_URL = settings.database_url.replace("survey_db", "survey_test_db")


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create test database tables once per session."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
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
