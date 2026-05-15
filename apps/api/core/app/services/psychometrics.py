"""Psychometrics service — measurement toolkit backend logic.

Wraps the pure-math psychometrics engine with database access for survey
response data and scale library norm comparison.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.analytics import _extract_question_defs
from ..core.psychometrics import (
    compute_split_half_reliability,
    compute_item_total_correlations,
    compute_kmo_bartlett,
    compute_construct_psychometrics,
    compute_cronbach_alpha,
)
from ..models.knowledge_scale import KnowledgeScale
from ..models.survey import Survey
from ..models.survey_response import SurveyResponse
from ..schemas.psychometrics import (
    ConstructDefinition,
    ConstructPsychometricsResult,
    ItemTotalCorrelationResult,
    ItemTotalItem,
    KmoBartlettResult,
    PsychometricReportResponse,
    ReliabilityNormComparisonResult,
    ReportSection,
    ScaleNormEntry,
    SplitHalfResult,
)


class PsychometricsService:
    """Psychometric analysis service for survey response data."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Data Fetching ──────────────────────────────────────────────────

    async def _get_analytics_data(
        self, survey_id: str
    ) -> tuple[Survey, list[dict], list[dict]]:
        """Fetch survey with its responses and question definitions."""
        result = await self.db.execute(
            select(Survey).where(Survey.id == survey_id)
        )
        survey = result.scalar_one_or_none()

        questions = _extract_question_defs(survey.json_content) if survey else []

        resp_result = await self.db.execute(
            select(SurveyResponse)
            .where(SurveyResponse.survey_id == survey_id)
            .order_by(SurveyResponse.submitted_at.asc())
        )
        response_rows = resp_result.scalars().all()

        response_dicts = [
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

    def _resolve_item_names(
        self,
        items_str: Optional[str],
        questions: list[dict],
    ) -> list[str]:
        """Parse comma-separated item names or auto-detect Likert items."""
        if items_str:
            return [n.strip() for n in items_str.split(",") if n.strip()]

        # Auto-detect Likert items
        likert_types = {"rating"}
        return [q["name"] for q in questions if q.get("type") in likert_types]

    # ── Split-Half ────────────────────────────────────────────────────

    async def compute_split_half(
        self,
        survey_id: str,
        items_str: Optional[str],
        method: str = "odd_even",
    ) -> SplitHalfResult:
        _, questions, responses = await self._get_analytics_data(survey_id)
        item_names = self._resolve_item_names(items_str, questions)

        complete = [r for r in responses if r.get("is_complete", True)]
        answers_list = [r["answers"] for r in complete]

        result = compute_split_half_reliability(answers_list, item_names, method)
        return SplitHalfResult(**result)

    # ── Item-Total ────────────────────────────────────────────────────

    async def compute_item_total(
        self,
        survey_id: str,
        items_str: Optional[str],
    ) -> ItemTotalCorrelationResult:
        _, questions, responses = await self._get_analytics_data(survey_id)
        item_names = self._resolve_item_names(items_str, questions)

        complete = [r for r in responses if r.get("is_complete", True)]
        answers_list = [r["answers"] for r in complete]

        result = compute_item_total_correlations(answers_list, item_names)
        return ItemTotalCorrelationResult(**result)

    # ── KMO & Bartlett ────────────────────────────────────────────────

    async def compute_kmo_bartlett(
        self,
        survey_id: str,
        items_str: Optional[str],
    ) -> KmoBartlettResult:
        _, questions, responses = await self._get_analytics_data(survey_id)
        item_names = self._resolve_item_names(items_str, questions)

        complete = [r for r in responses if r.get("is_complete", True)]
        answers_list = [r["answers"] for r in complete]

        result = compute_kmo_bartlett(answers_list, item_names)
        return KmoBartlettResult(**result)

    # ── Construct Psychometrics ───────────────────────────────────────

    async def compute_construct_psychometrics(
        self,
        survey_id: str,
        constructs: list[ConstructDefinition],
    ) -> ConstructPsychometricsResult:
        _, questions, responses = await self._get_analytics_data(survey_id)

        complete = [r for r in responses if r.get("is_complete", True)]
        answers_list = [r["answers"] for r in complete]

        result = compute_construct_psychometrics(
            answers_list,
            [c.model_dump() for c in constructs],
        )

        from ..schemas.psychometrics import (
            ConstructPsychometric,
            InterConstructCorrelation,
        )

        return ConstructPsychometricsResult(
            constructs=[ConstructPsychometric(**c) for c in result["constructs"]],
            inter_correlations=[
                InterConstructCorrelation(**ic) for ic in result["inter_correlations"]
            ],
        )

    # ── Psychometric Report ───────────────────────────────────────────

    async def generate_report(
        self,
        survey_id: str,
        items_str: Optional[str] = None,
        include_constructs: Optional[str] = None,
    ) -> PsychometricReportResponse:
        survey, questions, responses = await self._get_analytics_data(survey_id)
        item_names = self._resolve_item_names(items_str, questions)

        complete = [r for r in responses if r.get("is_complete", True)]
        answers_list = [r["answers"] for r in complete]
        total_all = len(responses)

        sections: list[ReportSection] = []

        # 1. Scale Description
        sections.append(ReportSection(
            title="量表基本信息",
            type="text",
            content={
                "text": (
                    f"问卷「{survey.title}」包含 {len(questions)} 个问题，"
                    f"共收到 {total_all} 份回答（其中 {len(complete)} 份完整回答）。"
                    f"以下分析基于 {len(item_names)} 个 Likert 量表题项，"
                    f"有效样本量为 {len(answers_list)} 份完整回答。"
                ),
                "item_names": item_names,
                "total_responses": total_all,
                "complete_responses": len(complete),
            },
        ))

        # 2. Reliability
        alpha_result = compute_cronbach_alpha(answers_list, item_names)
        sh_result = compute_split_half_reliability(answers_list, item_names)
        sections.append(ReportSection(
            title="信度分析",
            type="metric_card",
            content={
                "cronbach_alpha": alpha_result.get("alpha"),
                "interpretation": alpha_result.get("interpretation"),
                "n_items": len(item_names),
                "n_valid": alpha_result.get("n_valid_responses", 0),
                "split_half_spearman_brown": sh_result.get("spearman_brown"),
                "split_half_interpretation": sh_result.get("interpretation"),
            },
        ))

        # 3. Item Statistics
        it_result = compute_item_total_correlations(answers_list, item_names)
        sections.append(ReportSection(
            title="题项统计",
            type="table",
            content={
                "headers": ["题项", "题总相关(r)", "删除后α", "质量"],
                "rows": [
                    [
                        it["item_name"],
                        f'{it["corrected_item_total_r"]:.3f}',
                        f'{it["alpha_if_deleted"]:.3f}' if it["alpha_if_deleted"] else "N/A",
                        {"good": "良好", "moderate": "一般", "weak": "弱"}.get(it["flag"], it["flag"]),
                    ]
                    for it in it_result.get("items", [])
                ],
            },
        ))

        # 4. Factorability
        kmo_result = compute_kmo_bartlett(answers_list, item_names)
        sections.append(ReportSection(
            title="因子分析适宜性",
            type="metric_card",
            content={
                "kmo_overall": kmo_result.get("kmo_overall"),
                "kmo_interpretation": kmo_result.get("interpretation"),
                "bartlett_chi_square": kmo_result.get("bartlett_chi_square"),
                "bartlett_df": kmo_result.get("bartlett_df"),
                "bartlett_p_value": kmo_result.get("bartlett_p_value"),
                "bartlett_significant": (
                    kmo_result.get("bartlett_p_value", 1.0) < 0.05
                    if kmo_result.get("bartlett_p_value") is not None
                    else None
                ),
            },
        ))

        # 5. Construct validity (if constructs defined)
        if include_constructs:
            try:
                import json
                constructs_raw = json.loads(include_constructs)
                constructs = [ConstructDefinition(**c) for c in constructs_raw]
                const_result = compute_construct_psychometrics(
                    answers_list,
                    [c.model_dump() for c in constructs],
                )
                sections.append(ReportSection(
                    title="构念效度",
                    type="comparison_table",
                    content={
                        "constructs": const_result["constructs"],
                        "inter_correlations": const_result["inter_correlations"],
                    },
                ))
            except Exception:
                pass  # skip construct section on parse error

        from datetime import datetime, timezone

        return PsychometricReportResponse(
            survey_id=survey_id,
            survey_title=survey.title,
            sections=sections,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    # ── Norm Comparison ───────────────────────────────────────────────

    async def compare_reliability_norms(
        self,
        survey_id: str,
        items_str: Optional[str],
        discipline: Optional[str] = None,
        language: Optional[str] = None,
    ) -> ReliabilityNormComparisonResult:
        _, questions, responses = await self._get_analytics_data(survey_id)
        item_names = self._resolve_item_names(items_str, questions)

        complete = [r for r in responses if r.get("is_complete", True)]
        answers_list = [r["answers"] for r in complete]

        # Observed alpha
        alpha_result = compute_cronbach_alpha(answers_list, item_names)
        observed_alpha = alpha_result.get("alpha", 0.0)
        n_valid = alpha_result.get("n_valid_responses", 0)

        # Query matching scales from library
        q = select(KnowledgeScale).where(KnowledgeScale.cronbach_alpha.isnot(None))
        if discipline:
            q = q.where(KnowledgeScale.discipline == discipline)
        if language:
            q = q.where(KnowledgeScale.language == language)
        q = q.limit(20)
        scales = (await self.db.execute(q)).scalars().all()

        # Build comparison entries
        comparison_scales: list[ScaleNormEntry] = []
        for scale in scales:
            if scale.cronbach_alpha is None:
                continue
            diff = round(scale.cronbach_alpha - (observed_alpha or 0), 4)
            first_cite = (
                scale.citations[0].get("citation", "")
                if scale.citations and len(scale.citations) > 0
                else None
            )
            comparison_scales.append(ScaleNormEntry(
                scale_id=scale.id,
                scale_name=scale.name,
                discipline=scale.discipline,
                published_alpha=scale.cronbach_alpha,
                observed_alpha=observed_alpha or 0,
                difference=diff,
                n_published=(
                    scale.cronbach_alpha_history[-1].get("sample_n")
                    if scale.cronbach_alpha_history and len(scale.cronbach_alpha_history) > 0
                    else None
                ),
                citation=first_cite,
            ))

        # Sort by absolute difference (closest match first)
        comparison_scales.sort(key=lambda x: abs(x.difference))

        # Summary
        if not comparison_scales:
            summary = "量表库中未找到匹配的已发表常模。建议放宽学科或语言筛选条件。"
        else:
            closest = comparison_scales[0]
            alpha_str = f"{observed_alpha:.3f}" if observed_alpha else "N/A"
            pub_str = f"{closest.published_alpha:.3f}"
            if observed_alpha and closest.published_alpha:
                if abs(closest.difference) < 0.05:
                    summary = (
                        f"实测 α={alpha_str}，最接近的已发表量表「{closest.scale_name}」"
                        f"α={pub_str}，差值 {closest.difference:+.3f}，结果高度一致。"
                    )
                elif closest.difference > 0:
                    summary = (
                        f"实测 α={alpha_str}，接近但略低于「{closest.scale_name}」"
                        f"（α={pub_str}），建议检查题项质量和样本同质性。"
                    )
                else:
                    summary = (
                        f"实测 α={alpha_str}，与「{closest.scale_name}」"
                        f"（α={pub_str}）相比，差异在可接受范围。"
                    )
            else:
                summary = f"已找到 {len(comparison_scales)} 个已发表量表可供比较。"

        return ReliabilityNormComparisonResult(
            observed_alpha=observed_alpha or 0,
            n_items=len(item_names),
            n_valid=n_valid,
            comparison_scales=comparison_scales,
            summary=summary,
        )
