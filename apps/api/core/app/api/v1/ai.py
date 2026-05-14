"""AI generation API — SSE streaming and non-streaming endpoints.

Endpoints:
- POST /api/v1/ai/generate — Non-streaming survey generation
- POST /api/v1/ai/generate/stream — SSE streaming generation with progress
- POST /api/v1/ai/refine — Item refinement
- POST /api/v1/ai/estimate-cost — Pre-flight cost estimation
- GET  /api/v1/ai/evaluate/{survey_id} — SQP quality evaluation
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_optional_user
from ...database import get_db
from ...models.user import User
from ...schemas.ai_generation import (
    AiCostEstimate,
    AiGenerationResponse,
    ItemRefinementRequest,
    QualityCheckRequest,
    SqpQualitySummary,
    SurveyGenerationRequest,
)
from ...services.ai_generation import (
    AiGenerationService,
    estimate_cost,
    generate_survey,
    refine_items,
)

router = APIRouter(prefix="/ai", tags=["AI Generation"])


# ── Cost estimation (no auth required — informational) ────────────────


@router.post("/estimate-cost", response_model=AiCostEstimate)
async def estimate_generation_cost(request: SurveyGenerationRequest):
    """Estimate LLM token usage and cost before generating.

    No authentication required — this is informational only.
    DeepSeek costs ~¥0.01 per 20-item survey generation.
    """
    return estimate_cost(request)


# ── Non-streaming generation (authenticated) ───────────────────────────


@router.post("/generate", response_model=AiGenerationResponse)
async def generate_survey_nonstream(
    gen_request: SurveyGenerationRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Generate a complete academic survey (non-streaming).

    Returns the full survey JSON + SQP quality report.
    For real-time progress, use ``/generate/stream`` instead.
    """
    service = AiGenerationService(db)
    result = await service.generate_survey(gen_request, user_id=user.id)
    return result


# ── SSE streaming generation ───────────────────────────────────────────


@router.post("/generate/stream")
async def generate_survey_stream(
    gen_request: SurveyGenerationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Generate a survey with real-time SSE progress events.

    The client receives a stream of JSON events:
        event: progress
        data: {"stage": "generating", "message": "...", "progress_pct": 45}

        event: done
        data: {"stage": "done", "message": "完成", "progress_pct": 100, "data": {...}}

    Connect from the frontend using EventSource or fetch with
    ``Accept: text/event-stream``.
    """

    async def event_generator():
        service = AiGenerationService(db)
        try:
            async for event in service.generate_survey_stream(
                gen_request, user_id=user.id
            ):
                # Check for client disconnect
                if await request.is_disconnected():
                    break
                yield f"event: {event.stage}\ndata: {json.dumps(event.model_dump(), ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"event: error\ndata: {json.dumps({'stage': 'error', 'message': str(exc), 'progress_pct': 100}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


# ── Item refinement ────────────────────────────────────────────────────


@router.post("/refine", response_model=AiGenerationResponse)
async def refine_survey_items(
    ref_request: ItemRefinementRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Critique and improve individual survey items using AI."""
    service = AiGenerationService(db)
    result = await service.refine_items(ref_request, user_id=user.id)
    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.error,
        )
    return result


# ── SQP evaluation (on-demand, authenticated) ──────────────────────────


@router.get("/evaluate/{survey_id}", response_model=SqpQualitySummary)
async def evaluate_survey(
    survey_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Run SQP quality evaluation on an existing survey."""
    from ...core.sqp_evaluator import evaluate_survey_quality
    from ...models.survey import Survey

    survey = await db.get(Survey, survey_id)
    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")

    if not survey.structure:
        raise HTTPException(status_code=400, detail="问卷尚无内容")

    sqp_report = evaluate_survey_quality(
        {"survey": survey.structure}, survey_id=survey_id
    )

    return SqpQualitySummary(
        overall_quality=sqp_report.overall_quality,
        total_items=sqp_report.total_items,
        total_flags=sqp_report.total_flags,
        estimated_cronbach_alpha=sqp_report.estimated_cronbach_alpha,
        recommendation=sqp_report.recommendation,
        summary=sqp_report.summary,
    )


# ── Health check for AI service ───────────────────────────────────────


@router.get("/health")
async def ai_health():
    """Check AI service availability."""
    from ...config import settings

    has_deepseek = bool(settings.deepseek_api_key)
    return {
        "status": "ok" if has_deepseek else "no_api_key",
        "providers": {
            "deepseek": {
                "available": has_deepseek,
                "model": settings.deepseek_model,
                "base_url": settings.deepseek_base_url,
            },
        },
    }
