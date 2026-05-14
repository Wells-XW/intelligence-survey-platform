"""Survey analytics API endpoints.

All endpoints require at least viewer permission on the survey.
No LLM dependency — all computations are deterministic Python.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.analytics import (
    _extract_question_defs,
    _interpret_alpha,
    _is_categorical,
    _is_likert,
    _is_numeric,
    _is_text,
    compute_cronbach_alpha,
    compute_cross_tab,
    compute_descriptive,
    compute_frequencies,
    compute_response_quality,
    compute_text_summary,
)
from ...core.deps import check_survey_permission, get_current_user
from ...database import get_db
from ...models.survey import Survey
from ...models.survey_response import SurveyResponse
from ...models.user import User
from ...schemas.analytics import (
    CronbachAlphaResult,
    CrossTabResult,
    FrequencyItem,
    NumericStats,
    QuestionSummary,
    ResponseQualityResult,
    SurveySummaryResponse,
)

router = APIRouter(prefix="/surveys", tags=["analytics"])


# ── Helper: fetch responses + question defs ────────────────────────────


async def _get_analytics_data(
    survey_id: str,
    db: AsyncSession,
) -> tuple[Survey, list[dict], list[dict]]:
    """Fetch survey with its responses and question definitions."""
    result = await db.execute(select(Survey).where(Survey.id == survey_id))
    survey = result.scalar_one_or_none()
    if survey is None:
        raise HTTPException(status_code=404, detail="问卷不存在")

    questions = _extract_question_defs(survey.json_content)

    resp_result = await db.execute(
        select(SurveyResponse)
        .where(SurveyResponse.survey_id == survey_id)
        .order_by(SurveyResponse.submitted_at.asc())
    )
    response_rows = resp_result.scalars().all()

    response_dicts: list[dict] = [
        {
            "id": r.id,
            "answers": r.answers,
            "metadata": r.metadata_json,
            "is_complete": r.is_complete,
            "submitted_at": r.submitted_at,
        }
        for r in response_rows
    ]

    return survey, questions, response_dicts


# ── Summary Endpoint ──────────────────────────────────────────────────


@router.get("/{survey_id}/analytics/summary", response_model=SurveySummaryResponse)
async def get_analytics_summary(
    survey_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Full descriptive statistics for every question in the survey."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "viewer", db)

    survey, questions, responses = await _get_analytics_data(sid, db)

    # Complete responses only for analysis
    complete = [r for r in responses if r.get("is_complete", True)]
    answers_list = [r["answers"] for r in complete]
    total = len(responses)
    complete_count = len(complete)

    question_summaries: list[QuestionSummary] = []
    for q in questions:
        qname = q.get("name", "unknown")
        qtext = q.get("title", qname)
        qtype = q.get("type", "text")

        skipped = sum(1 for a in answers_list if a.get(qname) is None)
        total_answers = len(answers_list) - skipped

        summary = QuestionSummary(
            question_name=qname,
            question_text=qtext,
            question_type=qtype,
            total_answers=total_answers,
            skipped=skipped,
        )

        if _is_categorical(q) or qtype == "boolean":
            freqs = compute_frequencies(answers_list, q)
            summary.frequencies = [FrequencyItem(**f) for f in freqs]

        if _is_numeric(q):
            stats = compute_descriptive(answers_list, q)
            if stats:
                summary.numeric_stats = NumericStats(**stats)

        if _is_text(q):
            text_info = compute_text_summary(answers_list, q)
            summary.word_cloud = []
            summary.top_texts = text_info.get("top_texts", [])

        question_summaries.append(summary)

    return SurveySummaryResponse(
        survey_id=sid,
        survey_title=survey.title,
        total_responses=total,
        complete_responses=complete_count,
        partial_responses=total - complete_count,
        questions=question_summaries,
    )


# ── Reliability Endpoint ──────────────────────────────────────────────


@router.get(
    "/{survey_id}/analytics/reliability",
    response_model=list[CronbachAlphaResult],
)
async def get_reliability(
    survey_id: UUID,
    scale_items: Optional[str] = Query(
        default=None,
        description="Comma-separated question names for the scale. "
        "If omitted, auto-detects Likert-scale questions.",
    ),
    scale_name: str = Query(default="默认量表", description="Display name for the scale"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Compute Cronbach's alpha for a set of Likert-scale items.

    If ``scale_items`` is provided, computes alpha for those items only.
    Otherwise, auto-detects all Likert-scale (rating type) questions.
    """
    sid = str(survey_id)
    await check_survey_permission(sid, user, "viewer", db)

    _, questions, responses = await _get_analytics_data(sid, db)

    # Use user-specified items or auto-detect Likert items
    if scale_items:
        item_names = [name.strip() for name in scale_items.split(",") if name.strip()]
    else:
        item_names = [q["name"] for q in questions if _is_likert(q)]

    if not item_names:
        return []

    # Complete responses only
    complete = [r for r in responses if r.get("is_complete", True)]
    answers_list = [r["answers"] for r in complete]

    result = compute_cronbach_alpha(answers_list, item_names)

    return [
        CronbachAlphaResult(
            scale_name=scale_name,
            items=item_names,
            n_items=result["n_items"],
            n_valid_responses=result["n_valid_responses"],
            alpha=result["alpha"],
            item_variances=result["item_variances"],
            total_variance=result["total_variance"],
            interpretation=_interpret_alpha(result["alpha"]),
        )
    ]


# ── Cross-Tab Endpoint ────────────────────────────────────────────────


@router.get("/{survey_id}/analytics/cross-tab", response_model=CrossTabResult)
async def get_cross_tab(
    survey_id: UUID,
    q1: str = Query(..., description="Row question name"),
    q2: str = Query(..., description="Column question name"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Cross-tabulation of two categorical questions."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "viewer", db)

    _, questions, responses = await _get_analytics_data(sid, db)

    # Find question definitions
    q1_def = next((q for q in questions if q["name"] == q1), None)
    q2_def = next((q for q in questions if q["name"] == q2), None)

    if q1_def is None:
        raise HTTPException(status_code=404, detail=f"问题 '{q1}' 不存在")
    if q2_def is None:
        raise HTTPException(status_code=404, detail=f"问题 '{q2}' 不存在")

    complete = [r for r in responses if r.get("is_complete", True)]
    answers_list = [r["answers"] for r in complete]

    result = compute_cross_tab(answers_list, q1_def, q2_def)

    return CrossTabResult(
        row_question=q1,
        col_question=q2,
        row_labels=result["row_labels"],
        col_labels=result["col_labels"],
        matrix=result["matrix"],
        chi_square=result.get("chi_square"),
        n=result["n"],
    )


# ── Response Quality Endpoint ─────────────────────────────────────────


@router.get(
    "/{survey_id}/analytics/response-quality",
    response_model=ResponseQualityResult,
)
async def get_response_quality(
    survey_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Data quality diagnostics: completion rate, speeders, straightliners."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "viewer", db)

    _, questions, responses = await _get_analytics_data(sid, db)

    quality = compute_response_quality(responses, questions)

    return ResponseQualityResult(**quality)
