"""Health check endpoint."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Simple health check."""
    return {"status": "ok", "service": "intelligence-survey-platform"}
