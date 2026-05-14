"""FastAPI application factory and entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.v1.analytics import router as analytics_router
from .api.v1.auth import router as auth_router
from .api.v1.health import router as health_router
from .api.v1.responses import router as responses_router
from .api.v1.surveys import router as surveys_router
from .config import settings
from .database import Base, engine
from .middleware.rate_limit import RateLimitMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    # Startup: create tables (for MVP; use Alembic in production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown: dispose engine
    await engine.dispose()


app = FastAPI(
    title="Intelligence Survey Platform API",
    description="AI-driven intelligent online survey platform for academic research",
    version="0.1.0",
    lifespan=lifespan,
)

# Rate limiting — applied before CORS so abusive requests are rejected early
app.add_middleware(RateLimitMiddleware)

# CORS — explicit headers for security
origins = [o.strip() for o in settings.cors_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# API Routes
app.include_router(analytics_router, prefix="/api/v1")
app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(responses_router, prefix="/api/v1")
app.include_router(surveys_router, prefix="/api/v1")
