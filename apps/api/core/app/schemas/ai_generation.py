"""Pydantic schemas for AI survey generation API."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ── Request schemas ───────────────────────────────────────────────────


class SurveyGenerationRequest(BaseModel):
    """Request to generate a complete survey instrument."""

    topic: str = Field(
        ..., min_length=3, max_length=500,
        description="Broad research topic (e.g., '网络调查的代表性偏差')",
    )
    research_question: str = Field(
        ..., min_length=10, max_length=2000,
        description="Specific research question",
    )
    target_population: str = Field(
        ..., min_length=3, max_length=500,
        description="Target population description",
    )
    num_items: int = Field(
        default=20, ge=5, le=100,
        description="Target number of items (excluding demographics)",
    )
    language: str = Field(
        default="zh", pattern=r"^(zh|en)$",
        description="Survey language: zh (Chinese) or en (English)",
    )
    constructs: Optional[list[str]] = Field(
        default=None, max_length=10,
        description="Key constructs to measure",
    )
    existing_scales: Optional[list[str]] = Field(
        default=None,
        description="Names of existing scales to adapt",
    )
    methodology_notes: Optional[str] = Field(
        default=None, max_length=2000,
        description="Additional methodological requirements",
    )
    survey_id: Optional[str] = Field(
        default=None,
        description="Existing survey ID to populate (update mode)",
    )


class ItemRefinementRequest(BaseModel):
    """Request to critique and improve individual survey items."""

    survey_id: str = Field(..., description="Survey ID containing the items")
    item_ids: Optional[list[str]] = Field(
        default=None,
        description="Specific items to refine (omit for all items)",
    )
    focus_areas: Optional[list[str]] = Field(
        default=None,
        description="Aspects to focus on: bias, clarity, scale, relevance, cross-cultural",
    )
    language: str = Field(default="zh", pattern=r"^(zh|en)$")


class QualityCheckRequest(BaseModel):
    """Request AI-assisted response quality audit."""

    survey_id: str = Field(..., description="Survey ID to audit responses for")
    max_responses: int = Field(
        default=500, ge=1, le=5000,
        description="Maximum responses to analyze (for cost control)",
    )


class AiGenerateRequest(BaseModel):
    """Unified AI generation request for SSE streaming."""

    action: str = Field(
        ...,
        pattern=r"^(generate_survey|refine_items|check_quality|suggest_title)$",
        description="Type of AI generation to perform",
    )
    params: SurveyGenerationRequest | ItemRefinementRequest | QualityCheckRequest | \
        dict = Field(..., description="Action-specific parameters")


# ── Response schemas ──────────────────────────────────────────────────


class AiGenerationMeta(BaseModel):
    """Metadata about the AI generation call."""

    model: str = Field(..., description="LLM model used")
    provider: str = Field(..., description="LLM provider")
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    estimated_cost_cents: float = 0.0
    route_reasoning: str = ""


class SqpQualitySummary(BaseModel):
    """Summary of SQP quality evaluation."""

    overall_quality: float = Field(..., ge=0.0, le=1.0)
    total_items: int = 0
    total_flags: int = 0
    estimated_cronbach_alpha: float = 0.0
    recommendation: str = ""
    summary: str = ""


class AiGenerationResponse(BaseModel):
    """Complete AI generation response."""

    survey_json: Optional[dict] = Field(
        default=None, description="Generated survey in JSON format"
    )
    sqp_report: Optional[SqpQualitySummary] = Field(default=None)
    meta: AiGenerationMeta = Field(default_factory=AiGenerationMeta)
    success: bool = True
    error: Optional[str] = None


# ── SSE event schemas ────────────────────────────────────────────────


class SseProgressEvent(BaseModel):
    """Progress event sent during SSE streaming."""

    stage: str = Field(
        ..., description="Current stage: routing, generating, evaluating, done, error"
    )
    message: str = Field(..., description="Human-readable progress message")
    progress_pct: int = Field(default=0, ge=0, le=100)
    data: Optional[dict] = Field(default=None, description="Stage-specific payload")


class AiCostEstimate(BaseModel):
    """Pre-generation cost estimate for user confirmation."""

    estimated_tokens_input: int = 0
    estimated_tokens_output: int = 0
    estimated_cost_cents: float = 0.0
    estimated_cost_rmb: float = 0.0
    model: str = "deepseek-chat"
    provider: str = "deepseek"
    # DeepSeek costs ~¥0.02 per survey generation (vs ¥0.40 for GPT-4o)
    is_low_cost: bool = True
    message: str = ""
