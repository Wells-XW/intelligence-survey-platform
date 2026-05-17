"""Serve the integration usage guide as plain markdown text.

The guide lives at ``apps/api/core/app/static/integration-guide.md`` and
covers four common integration flows (auth, list surveys, register a
webhook, start an export) with cURL plus Python (httpx) examples. It is
linked from the FastAPI app description so it is reachable from the
Swagger UI page (Req 1.6).
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

router = APIRouter(prefix="/integration-guide", tags=["docs"])

_GUIDE_PATH = (
    Path(__file__).resolve().parent.parent.parent / "static" / "integration-guide.md"
)


@router.get(
    "/",
    response_class=PlainTextResponse,
    summary="Integration usage guide",
    description=(
        "Returns the integration usage guide as markdown text "
        "(media type ``text/markdown``). Reachable from the Swagger "
        "UI page via the link in the API description."
    ),
    responses={
        200: {
            "content": {
                "text/markdown": {
                    "example": (
                        "# Integration Guide\n\n"
                        "## Authenticate\n"
                        "```\n"
                        "curl -X POST https://api.example.com/api/v1/auth/login \\\n"
                        "  -d 'username=you@example.com&password=...'\n"
                        "```\n"
                    )
                }
            },
            "description": "Integration guide markdown.",
        },
        404: {"description": "Guide file is missing on this deployment."},
    },
)
async def get_integration_guide() -> PlainTextResponse:
    """Return the integration guide markdown.

    Returns:
        PlainTextResponse: the guide content with media type
        ``text/markdown; charset=utf-8``.

    Raises:
        HTTPException: 404 when the static guide file cannot be located.
    """
    if not _GUIDE_PATH.exists():
        raise HTTPException(status_code=404, detail="Guide not found")
    text = _GUIDE_PATH.read_text(encoding="utf-8")
    return PlainTextResponse(content=text, media_type="text/markdown; charset=utf-8")
