"""Health check endpoint.

Health is an internal-only operational probe consumed by uptime checks
and container orchestrators, not part of the public integration surface.
The router is therefore excluded from the published OpenAPI schema via
``include_in_schema=False`` on each route so external integrators
browsing /api/v1/docs see only the public, supported endpoints.
"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health", include_in_schema=False)
async def health_check():
    """Simple health check.

    Returns:
        A minimal status payload used by uptime and liveness probes.
    """
    return {"status": "ok", "service": "intelligence-survey-platform"}
