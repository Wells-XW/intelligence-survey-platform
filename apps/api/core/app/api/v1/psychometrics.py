"""Psychometrics API endpoints — measurement toolkit.

All endpoints require at least viewer permission on the survey.
No LLM dependency — all computations are deterministic Python via
the psychometrics engine.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import check_survey_permission, get_current_user
from ...database import get_db
from ...models.user import User
from ...schemas.psychometrics import (
    ConstructPsychometricsRequest,
    ConstructPsychometricsResult,
    ItemTotalCorrelationResult,
    KmoBartlettResult,
    PsychometricReportResponse,
    ReliabilityNormComparisonResult,
    SplitHalfResult,
)
from ...services.psychometrics import PsychometricsService

router = APIRouter(prefix="/surveys", tags=["psychometrics"])


async def _get_service(db: AsyncSession = Depends(get_db)) -> PsychometricsService:
    return PsychometricsService(db)


# ── Split-Half Reliability ────────────────────────────────────────────


@router.get("/{survey_id}/psychometrics/split-half", response_model=SplitHalfResult)
async def get_split_half(
    survey_id: UUID,
    items: Optional[str] = Query(
        default=None,
        description="Comma-separated item names. Auto-detects Likert items if omitted.",
    ),
    method: str = Query(
        default="odd_even",
        description="Split method: odd_even or first_second",
    ),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    service: PsychometricsService = Depends(_get_service),
):
    """Compute split-half reliability with Spearman-Brown correction."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "viewer", db)

    try:
        return await service.compute_split_half(sid, items, method)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分半信度计算失败: {str(e)}")


# ── Item-Total Correlations ───────────────────────────────────────────


@router.get(
    "/{survey_id}/psychometrics/item-total",
    response_model=ItemTotalCorrelationResult,
)
async def get_item_total(
    survey_id: UUID,
    items: Optional[str] = Query(
        default=None,
        description="Comma-separated item names. Auto-detects Likert items if omitted.",
    ),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    service: PsychometricsService = Depends(_get_service),
):
    """Compute corrected item-total correlations and alpha-if-deleted."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "viewer", db)

    try:
        return await service.compute_item_total(sid, items)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"题总相关计算失败: {str(e)}")


# ── KMO & Bartlett ────────────────────────────────────────────────────


@router.get(
    "/{survey_id}/psychometrics/kmo-bartlett",
    response_model=KmoBartlettResult,
)
async def get_kmo_bartlett(
    survey_id: UUID,
    items: Optional[str] = Query(
        default=None,
        description="Comma-separated item names. Auto-detects Likert items if omitted.",
    ),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    service: PsychometricsService = Depends(_get_service),
):
    """Compute KMO sampling adequacy and Bartlett's test of sphericity."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "viewer", db)

    try:
        return await service.compute_kmo_bartlett(sid, items)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"KMO/Bartlett 检验失败: {str(e)}")


# ── Construct Psychometrics ───────────────────────────────────────────


@router.post(
    "/{survey_id}/psychometrics/constructs",
    response_model=ConstructPsychometricsResult,
)
async def analyze_constructs(
    survey_id: UUID,
    body: ConstructPsychometricsRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    service: PsychometricsService = Depends(_get_service),
):
    """Analyze multi-construct psychometrics with inter-construct correlations."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "viewer", db)

    if not body.constructs:
        raise HTTPException(status_code=400, detail="至少需要定义一个构念")

    try:
        return await service.compute_construct_psychometrics(sid, body.constructs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"构念分析失败: {str(e)}")


# ── Psychometric Report ───────────────────────────────────────────────


@router.get(
    "/{survey_id}/psychometrics/report",
    response_model=PsychometricReportResponse,
)
async def get_report(
    survey_id: UUID,
    items: Optional[str] = Query(
        default=None,
        description="Comma-separated item names. Auto-detects Likert items if omitted.",
    ),
    include_constructs: Optional[str] = Query(
        default=None,
        description="JSON-encoded list of construct definitions",
    ),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    service: PsychometricsService = Depends(_get_service),
):
    """Generate a comprehensive APA-style psychometric report."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "viewer", db)

    try:
        return await service.generate_report(sid, items, include_constructs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"报告生成失败: {str(e)}")


# ── Norm Comparison ───────────────────────────────────────────────────


@router.get(
    "/{survey_id}/psychometrics/norm-comparison",
    response_model=ReliabilityNormComparisonResult,
)
async def compare_norms(
    survey_id: UUID,
    items: Optional[str] = Query(
        default=None,
        description="Comma-separated item names. Auto-detects Likert items if omitted.",
    ),
    discipline: Optional[str] = Query(
        default=None,
        description="Filter comparison scales by discipline",
    ),
    language: Optional[str] = Query(
        default=None,
        description="Filter comparison scales by language (zh/en)",
    ),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    service: PsychometricsService = Depends(_get_service),
):
    """Compare observed scale reliability against published scale norms."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "viewer", db)

    try:
        return await service.compare_reliability_norms(
            sid, items, discipline, language
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"常模比较失败: {str(e)}")
