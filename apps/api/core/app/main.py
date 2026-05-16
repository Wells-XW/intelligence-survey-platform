"""FastAPI application factory and entry point."""

from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from .api.v1.admin import router as admin_router
from .api.v1.ai import router as ai_router
from .api.v1.analytics import router as analytics_router
from .api.v1.api_keys import router as api_keys_router
from .api.v1.auth import router as auth_router
from .api.v1.compliance import (
    compliance_audit_router,
    router as compliance_router,
)
from .api.v1.distribution import router as distribution_router
from .api.v1.distribution import public_router as distribution_public_router
from .api.v1.exports import router as exports_router
from .api.v1.health import router as health_router
from .api.v1.integration_guide import router as integration_guide_router
from .api.v1.knowledge_base import router as kb_router
from .api.v1.permissions import (
    standalone_router as invitations_standalone_router,
    survey_invitations_router,
    survey_permissions_router,
    user_search_router,
)
from .api.v1.psychometrics import router as psychometrics_router
from .api.v1.responses import router as responses_router
from .api.v1.surveys import router as surveys_router
from .api.v1.versions import router as versions_router
from .api.v1.webhooks import router as webhooks_router
from .config import settings
from .core.seed_data import seed_scales_and_entries
from .database import Base, async_session, engine
from .middleware.rate_limit import RateLimitMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    # Startup: create tables (for MVP; use Alembic in production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Seed knowledge base with default scales and guides (idempotent)
    async with async_session() as session:
        await seed_scales_and_entries(session)
        await session.commit()
    yield
    # Shutdown: dispose engine
    await engine.dispose()


app = FastAPI(
    title="Intelligence Survey Platform API",
    description=(
        "AI-driven intelligent online survey platform for academic research. "
        "Two authentication paths are supported: Bearer JWT (interactive UI) "
        "and X-API-Key (machine integrators).\n\n"
        "**Integration usage guide:** "
        "[/api/v1/integration-guide](/api/v1/integration-guide/) — worked "
        "examples in cURL and Python (httpx) for authentication, listing "
        "surveys, registering a webhook subscription, and starting an export "
        "job."
    ),
    version="0.1.0",
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
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
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)

# API Routes
app.include_router(admin_router, prefix="/api/v1")
app.include_router(ai_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")
app.include_router(compliance_router, prefix="/api/v1")
app.include_router(compliance_audit_router, prefix="/api/v1")
app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(api_keys_router, prefix="/api/v1")
app.include_router(kb_router, prefix="/api/v1")
app.include_router(distribution_public_router, prefix="/api/v1")
app.include_router(distribution_router, prefix="/api/v1")
app.include_router(exports_router, prefix="/api/v1")
app.include_router(integration_guide_router, prefix="/api/v1")
app.include_router(psychometrics_router, prefix="/api/v1")
app.include_router(responses_router, prefix="/api/v1")
app.include_router(surveys_router, prefix="/api/v1")
app.include_router(versions_router, prefix="/api/v1")
app.include_router(webhooks_router, prefix="/api/v1")
app.include_router(survey_permissions_router, prefix="/api/v1")
app.include_router(survey_invitations_router, prefix="/api/v1")
app.include_router(invitations_standalone_router, prefix="/api/v1")
app.include_router(user_search_router, prefix="/api/v1")


def custom_openapi() -> Dict[str, Any]:
    """Generate the OpenAPI schema with both supported auth schemes injected.

    The platform accepts two authentication paths on protected routes:
    a Bearer JWT (interactive UI) and an X-API-Key header (machine
    integrators). This helper extends the FastAPI-generated schema with
    matching ``securitySchemes`` entries and applies them globally so
    Swagger UI and ReDoc list both as accepted alternatives on every
    route that depends on ``get_principal``.

    Returns:
        The fully populated OpenAPI 3.x schema. The result is cached on
        ``app.openapi_schema`` so subsequent requests are served without
        regeneration.
    """
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    components = schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": (
            "JWT access token issued by /api/v1/auth/login. "
            "Send as 'Authorization: Bearer <token>'."
        ),
    }
    security_schemes["ApiKeyAuth"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": (
            "Long-lived API key issued via /api/v1/api-keys. "
            "Format: sk_<env>_<24 url-safe chars>. "
            "Either BearerAuth or ApiKeyAuth is accepted on protected routes."
        ),
    }

    # Apply both schemes globally as accepted alternatives. OpenAPI semantics:
    # the outer list is OR; an empty inner object means "no auth required" and
    # is intentionally omitted so unauthenticated routes opt out via their own
    # per-operation override (FastAPI does this automatically when no security
    # dependency is declared).
    schema["security"] = [{"BearerAuth": []}, {"ApiKeyAuth": []}]

    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi  # type: ignore[method-assign]
