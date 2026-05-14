"""AI generation orchestrator service.

Handles the full lifecycle of an AI generation request:
1. Cost estimation
2. Multi-model routing decision
3. Prompt construction (methodology-constrained)
4. LLM call execution
5. SQP quality evaluation
6. Result persistence & audit logging
"""

from __future__ import annotations

import json
import time
from typing import AsyncIterator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.ai_router import (
    AiCallResult,
    ModelTarget,
    RouteDecision,
    TaskCategory,
    execute_ai_call,
)
from ..core.prompts import (
    SURVEY_GENERATION_SYSTEM,
    build_item_refinement_prompt,
    build_quality_check_prompt,
    build_survey_generation_prompt,
    ITEM_REFINEMENT_SYSTEM,
    QUALITY_CHECK_SYSTEM,
)
from ..core.sqp_evaluator import evaluate_survey_quality, format_sqp_report, SqpSurveyReport
from ..models.ai_generation_log import AiGenerationLog
from ..models.survey import Survey
from ..schemas.ai_generation import (
    AiCostEstimate,
    AiGenerationMeta,
    AiGenerationResponse,
    ItemRefinementRequest,
    QualityCheckRequest,
    SqpQualitySummary,
    SseProgressEvent,
    SurveyGenerationRequest,
)


class AiGenerationService:
    """Orchestrates AI-powered survey generation with methodology constraints."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Cost estimation ───────────────────────────────────────────

    def estimate_cost(
        self,
        request: SurveyGenerationRequest,
    ) -> AiCostEstimate:
        """Estimate LLM cost before making the call.

        For DeepSeek, a 20-item survey generation costs approximately:
        - Input: ~3,000 tokens (system prompt + user prompt)
        - Output: ~2,500 tokens (structured JSON)
        - Cost: ~$0.00112 = ~¥0.008

        This is 20-40× cheaper than GPT-4o and ~5× cheaper than Claude.
        """
        # Rough token estimation based on input length
        input_chars = len(request.research_question) + len(request.topic) + 1000
        estimated_input = int(input_chars * 0.4)  # ~0.4 tokens per Chinese char
        estimated_output = request.num_items * 100  # ~100 tokens per item

        # DeepSeek pricing per 1K tokens
        cost_cents = (
            (estimated_input / 1_000_000) * 0.14
            + (estimated_output / 1_000_000) * 0.28
        ) * 100

        cost_rmb = round(cost_cents * 0.073, 4)  # 1 cent ≈ ¥0.073

        return AiCostEstimate(
            estimated_tokens_input=estimated_input,
            estimated_tokens_output=estimated_output,
            estimated_cost_cents=round(cost_cents, 4),
            estimated_cost_rmb=cost_rmb,
            model="deepseek-chat",
            provider="deepseek",
            is_low_cost=True,
            message=f"预估消耗 ~{estimated_input + estimated_output} tokens，约 ¥{cost_rmb}",
        )

    # ── Full generation pipeline ──────────────────────────────────

    async def generate_survey(
        self,
        request: SurveyGenerationRequest,
        user_id: Optional[str] = None,
    ) -> AiGenerationResponse:
        """Execute the full survey generation pipeline.

        1. Build methodology-constrained prompt
        2. Route to optimal model (DeepSeek for Chinese)
        3. Call LLM
        4. Parse and validate JSON output
        5. Run SQP quality evaluation
        6. Persist to database
        7. Log audit trail
        """
        # Build prompt
        user_prompt = build_survey_generation_prompt(
            topic=request.topic,
            research_question=request.research_question,
            target_population=request.target_population,
            num_items=request.num_items,
            language=request.language,
            constructs=request.constructs,
            existing_scales=request.existing_scales,
            methodology_notes=request.methodology_notes,
        )

        # Execute AI call
        result, decision = await execute_ai_call(
            system_prompt=SURVEY_GENERATION_SYSTEM,
            user_prompt=user_prompt,
            task=TaskCategory.SURVEY_GENERATION,
            has_chinese=(request.language == "zh"),
        )

        if not result.success:
            # Log failed attempt
            await self._log_generation(
                user_id=user_id,
                survey_id=request.survey_id,
                result=result,
                decision=decision,
                status="error",
            )
            return AiGenerationResponse(
                success=False,
                error=result.error_message or "AI 生成失败，请稍后重试",
                meta=AiGenerationMeta(
                    model=result.model,
                    provider=result.provider,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    total_tokens=result.prompt_tokens + result.completion_tokens,
                    latency_ms=result.latency_ms,
                    estimated_cost_cents=result.estimated_cost_cents,
                    route_reasoning=decision.reasoning,
                ),
            )

        # Parse JSON output
        try:
            survey_json = json.loads(result.content)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            import re
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", result.content)
            if match:
                try:
                    survey_json = json.loads(match.group(1))
                except json.JSONDecodeError:
                    return AiGenerationResponse(
                        success=False,
                        error="AI 返回的不是有效 JSON，请重试",
                        meta=AiGenerationMeta(
                            model=result.model,
                            provider=result.provider,
                            total_tokens=result.prompt_tokens + result.completion_tokens,
                            latency_ms=result.latency_ms,
                            estimated_cost_cents=result.estimated_cost_cents,
                            route_reasoning=decision.reasoning,
                        ),
                    )
            else:
                return AiGenerationResponse(
                    success=False,
                    error="AI 返回的不是有效 JSON，请重试",
                    meta=AiGenerationMeta(
                        model=result.model,
                        provider=result.provider,
                        total_tokens=result.prompt_tokens + result.completion_tokens,
                        latency_ms=result.latency_ms,
                        estimated_cost_cents=result.estimated_cost_cents,
                        route_reasoning=decision.reasoning,
                    ),
                )

        # Run SQP quality evaluation
        sqp_report = evaluate_survey_quality(survey_json)
        sqp_summary = SqpQualitySummary(
            overall_quality=sqp_report.overall_quality,
            total_items=sqp_report.total_items,
            total_flags=sqp_report.total_flags,
            estimated_cronbach_alpha=sqp_report.estimated_cronbach_alpha,
            recommendation=sqp_report.recommendation,
            summary=sqp_report.summary,
        )

        # If updating an existing survey, save the generated content
        if request.survey_id:
            survey = await self.db.get(Survey, request.survey_id)
            if survey:
                survey.structure = survey_json.get("survey", survey_json)
                survey.title = (
                    survey_json.get("survey", survey_json).get("title")
                    or request.topic
                )
                await self.db.commit()

        # Log generation
        await self._log_generation(
            user_id=user_id,
            survey_id=request.survey_id,
            result=result,
            decision=decision,
            status="success",
        )

        return AiGenerationResponse(
            survey_json=survey_json,
            sqp_report=sqp_summary,
            meta=AiGenerationMeta(
                model=result.model,
                provider=result.provider,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                total_tokens=result.prompt_tokens + result.completion_tokens,
                latency_ms=result.latency_ms,
                estimated_cost_cents=result.estimated_cost_cents,
                route_reasoning=decision.reasoning,
            ),
            success=True,
        )

    # ── Item refinement ───────────────────────────────────────────

    async def refine_items(
        self,
        request: ItemRefinementRequest,
        user_id: Optional[str] = None,
    ) -> AiGenerationResponse:
        """Critique and improve individual survey items."""
        # Load existing survey items
        survey = await self.db.get(Survey, request.survey_id)
        if not survey:
            return AiGenerationResponse(
                success=False, error="问卷不存在"
            )

        items_json = json.dumps(survey.structure or {}, ensure_ascii=False, indent=2)
        user_prompt = build_item_refinement_prompt(
            items_json=items_json,
            language=request.language,
            focus_areas=request.focus_areas,
        )

        result, decision = await execute_ai_call(
            system_prompt=ITEM_REFINEMENT_SYSTEM,
            user_prompt=user_prompt,
            task=TaskCategory.ITEM_REFINEMENT,
            has_chinese=(request.language == "zh"),
        )

        if not result.success:
            await self._log_generation(
                user_id=user_id,
                survey_id=request.survey_id,
                result=result,
                decision=decision,
                status="error",
            )
            return AiGenerationResponse(
                success=False, error=result.error_message or "AI 优化失败"
            )

        try:
            refinement_json = json.loads(result.content)
        except json.JSONDecodeError:
            import re
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", result.content)
            if match:
                try:
                    refinement_json = json.loads(match.group(1))
                except json.JSONDecodeError:
                    return AiGenerationResponse(
                        success=False, error="AI 返回的不是有效 JSON"
                    )
            else:
                return AiGenerationResponse(
                    success=False, error="AI 返回的不是有效 JSON"
                )

        await self._log_generation(
            user_id=user_id,
            survey_id=request.survey_id,
            result=result,
            decision=decision,
            status="success",
            request_type="refine_items",
        )

        return AiGenerationResponse(
            survey_json=refinement_json,
            meta=AiGenerationMeta(
                model=result.model,
                provider=result.provider,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                total_tokens=result.prompt_tokens + result.completion_tokens,
                latency_ms=result.latency_ms,
                estimated_cost_cents=result.estimated_cost_cents,
                route_reasoning=decision.reasoning,
            ),
            success=True,
        )

    # ── Streaming generation (SSE) ────────────────────────────────

    async def generate_survey_stream(
        self,
        request: SurveyGenerationRequest,
        user_id: Optional[str] = None,
    ) -> AsyncIterator[SseProgressEvent]:
        """Stream the survey generation process via SSE events.

        Yields progress events at each stage so the frontend can
        show real-time status updates to the user.
        """
        # Stage 1: Cost estimate
        yield SseProgressEvent(
            stage="estimating",
            message="正在估算生成成本...",
            progress_pct=5,
        )
        cost = self.estimate_cost(request)
        yield SseProgressEvent(
            stage="estimated",
            message=f"预估成本约 ¥{cost.estimated_cost_rmb}（约 {cost.estimated_tokens_input + cost.estimated_tokens_output} tokens）",
            progress_pct=10,
            data={"cost": cost.model_dump()},
        )

        # Stage 2: Build prompt
        yield SseProgressEvent(
            stage="prompting",
            message="正在构建方法学约束提示词...",
            progress_pct=15,
        )
        user_prompt = build_survey_generation_prompt(
            topic=request.topic,
            research_question=request.research_question,
            target_population=request.target_population,
            num_items=request.num_items,
            language=request.language,
            constructs=request.constructs,
            existing_scales=request.existing_scales,
            methodology_notes=request.methodology_notes,
        )

        # Stage 3: Route to model
        yield SseProgressEvent(
            stage="routing",
            message="正在选择最优模型...",
            progress_pct=20,
        )

        # Stage 4: Generate (this is the slow part)
        yield SseProgressEvent(
            stage="generating",
            message="AI 正在生成问卷...（通常需要 10-30 秒）",
            progress_pct=25,
        )

        result, decision = await execute_ai_call(
            system_prompt=SURVEY_GENERATION_SYSTEM,
            user_prompt=user_prompt,
            task=TaskCategory.SURVEY_GENERATION,
            has_chinese=(request.language == "zh"),
        )

        if not result.success:
            await self._log_generation(
                user_id=user_id, survey_id=request.survey_id,
                result=result, decision=decision, status="error",
            )
            yield SseProgressEvent(
                stage="error",
                message=f"生成失败: {result.error_message}",
                progress_pct=100,
                data={"error": result.error_message},
            )
            return

        yield SseProgressEvent(
            stage="generated",
            message=f"生成完成（{result.total_tokens} tokens, {result.latency_ms}ms）",
            progress_pct=70,
        )

        # Stage 5: Parse JSON
        yield SseProgressEvent(
            stage="parsing",
            message="正在解析生成的问卷...",
            progress_pct=75,
        )

        try:
            survey_json = json.loads(result.content)
        except json.JSONDecodeError:
            import re
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", result.content)
            if match:
                try:
                    survey_json = json.loads(match.group(1))
                except json.JSONDecodeError:
                    yield SseProgressEvent(
                        stage="error",
                        message="AI 返回格式异常，请重试",
                        progress_pct=100,
                    )
                    return
            else:
                yield SseProgressEvent(
                    stage="error",
                    message="AI 返回格式异常，请重试",
                    progress_pct=100,
                )
                return

        # Stage 6: SQP evaluation
        yield SseProgressEvent(
            stage="evaluating",
            message="正在评估问卷质量（SQP v2.1）...",
            progress_pct=85,
        )

        sqp_report = evaluate_survey_quality(survey_json)

        yield SseProgressEvent(
            stage="evaluated",
            message=f"质量评估完成: {sqp_report.recommendation} (得分 {sqp_report.overall_quality:.2f})",
            progress_pct=95,
            data={
                "sqp": {
                    "overall_quality": sqp_report.overall_quality,
                    "total_flags": sqp_report.total_flags,
                    "recommendation": sqp_report.recommendation,
                    "summary": sqp_report.summary,
                }
            },
        )

        # Stage 7: Persist
        if request.survey_id:
            survey = await self.db.get(Survey, request.survey_id)
            if survey:
                survey.structure = survey_json.get("survey", survey_json)
                survey.title = (
                    survey_json.get("survey", survey_json).get("title")
                    or request.topic
                )
                await self.db.commit()

        await self._log_generation(
            user_id=user_id,
            survey_id=request.survey_id,
            result=result,
            decision=decision,
            status="success",
        )

        yield SseProgressEvent(
            stage="done",
            message="问卷生成完成！",
            progress_pct=100,
            data={
                "survey_json": survey_json,
                "sqp": {
                    "overall_quality": sqp_report.overall_quality,
                    "total_flags": sqp_report.total_flags,
                    "recommendation": sqp_report.recommendation,
                },
                "meta": {
                    "model": result.model,
                    "provider": result.provider,
                    "tokens": result.prompt_tokens + result.completion_tokens,
                    "cost_cents": result.estimated_cost_cents,
                },
            },
        )

    # ── Audit logging ─────────────────────────────────────────────

    async def _log_generation(
        self,
        user_id: Optional[str],
        survey_id: Optional[str],
        result: AiCallResult,
        decision: RouteDecision,
        status: str,
        request_type: str = "generate_survey",
    ) -> None:
        """Create an immutable audit log entry for this AI call."""
        log = AiGenerationLog(
            user_id=user_id,
            survey_id=survey_id,
            model=result.model,
            provider=result.provider,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.prompt_tokens + result.completion_tokens,
            latency_ms=result.latency_ms,
            estimated_cost_cents=result.estimated_cost_cents,
            request_type=request_type,
            status=status,
            error_message=result.error_message,
        )
        self.db.add(log)
        await self.db.commit()


# ── Module-level convenience functions ────────────────────────────────


# Singleton-like service access pattern (db is injected per-request)
def get_service(db: AsyncSession) -> AiGenerationService:
    """Create an AiGenerationService bound to a database session.

    Usage in FastAPI endpoints:
        service = get_service(db)
        result = await service.generate_survey(request, user_id=user.id)
    """
    return AiGenerationService(db)


async def generate_survey(
    db: AsyncSession,
    request: SurveyGenerationRequest,
    user_id: Optional[str] = None,
) -> AiGenerationResponse:
    """Convenience wrapper for quick non-streaming generation."""
    return await AiGenerationService(db).generate_survey(request, user_id)


async def refine_items(
    db: AsyncSession,
    request: ItemRefinementRequest,
    user_id: Optional[str] = None,
) -> AiGenerationResponse:
    """Convenience wrapper for item refinement."""
    return await AiGenerationService(db).refine_items(request, user_id)


def estimate_cost(request: SurveyGenerationRequest) -> AiCostEstimate:
    """Convenience wrapper for cost estimation (no DB needed)."""
    # Create a dummy service — cost estimation is stateless
    return AiGenerationService.__new__(AiGenerationService).estimate_cost(request)
