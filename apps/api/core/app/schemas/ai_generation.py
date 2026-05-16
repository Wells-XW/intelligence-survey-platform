"""Pydantic schemas for AI survey generation API."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


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

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "topic": "学术诚信与研究生导师指导",
                    "research_question": (
                        "硕博研究生对当前学术诚信制度的认知是否随导师指导"
                        "频率而变化？"
                    ),
                    "target_population": "中国大陆 985/211 高校在读硕士与博士",
                    "num_items": 22,
                    "language": "zh",
                    "constructs": ["学术诚信认知", "导师指导满意度"],
                    "existing_scales": ["ACI-CN-2019"],
                    "methodology_notes": "至少包含 1 道反向计分项与 1 道注意力检查项",
                    "survey_id": None,
                }
            ]
        }
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

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                    "item_ids": ["q3", "q7"],
                    "focus_areas": ["bias", "clarity"],
                    "language": "zh",
                }
            ]
        }
    )


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

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "overall_quality": 0.82,
                    "total_items": 22,
                    "total_flags": 3,
                    "estimated_cronbach_alpha": 0.81,
                    "recommendation": "可发布，建议复核 q3 与 q14 的措辞",
                    "summary": (
                        "整体质量良好。3 处 SQP 标记主要集中于双重否定与"
                        "复合提问，建议重写 q3。"
                    ),
                }
            ]
        }
    )


class AiGenerationResponse(BaseModel):
    """Complete AI generation response."""

    survey_json: Optional[dict] = Field(
        default=None, description="Generated survey in JSON format"
    )
    sqp_report: Optional[SqpQualitySummary] = Field(default=None)
    meta: AiGenerationMeta = Field(default_factory=AiGenerationMeta)
    success: bool = True
    error: Optional[str] = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "survey_json": {
                        "pages": [
                            {
                                "name": "page1",
                                "elements": [
                                    {
                                        "type": "rating",
                                        "name": "q1",
                                        "title": "整体而言，您对当前学术诚信制度的满意度如何？",
                                        "rateMin": 1,
                                        "rateMax": 5,
                                    }
                                ],
                            }
                        ]
                    },
                    "sqp_report": {
                        "overall_quality": 0.82,
                        "total_items": 22,
                        "total_flags": 3,
                        "estimated_cronbach_alpha": 0.81,
                        "recommendation": "可发布，建议复核 q3 与 q14 的措辞",
                        "summary": "整体质量良好。",
                    },
                    "meta": {
                        "model": "deepseek-chat",
                        "provider": "deepseek",
                        "prompt_tokens": 1840,
                        "completion_tokens": 2310,
                        "total_tokens": 4150,
                        "latency_ms": 8240,
                        "estimated_cost_cents": 1.4,
                        "route_reasoning": "task=survey_generation; tier=STANDARD",
                    },
                    "success": True,
                    "error": None,
                }
            ]
        }
    )


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

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "estimated_tokens_input": 1800,
                    "estimated_tokens_output": 2200,
                    "estimated_cost_cents": 1.3,
                    "estimated_cost_rmb": 0.013,
                    "model": "deepseek-chat",
                    "provider": "deepseek",
                    "is_low_cost": True,
                    "message": "约 ¥0.013，远低于 GPT-4o 的 ¥0.40。",
                }
            ]
        }
    )
