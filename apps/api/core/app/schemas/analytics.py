"""Pydantic v2 schemas for survey analytics responses."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ── Descriptive Statistics ────────────────────────────────────────────


class FrequencyItem(BaseModel):
    """A single categorical value and its count/percentage."""

    value: str
    count: int
    percentage: float = Field(description="0-100 scale")


class NumericStats(BaseModel):
    """Descriptive statistics for numeric/rating questions."""

    mean: float
    median: float
    mode: list[float]
    std_dev: float
    min_value: float
    max_value: float
    n: int


class QuestionSummary(BaseModel):
    """Per-question analysis result."""

    question_name: str
    question_text: str
    question_type: str  # radiogroup, checkbox, rating, text, etc.
    total_answers: int
    skipped: int
    # Present for categorical questions
    frequencies: Optional[list[FrequencyItem]] = None
    # Present for numeric/rating questions
    numeric_stats: Optional[NumericStats] = None
    # Present for open-ended text questions
    word_cloud: Optional[list[dict[str, object]]] = None
    # Common text responses (top 5 unique, for short text)
    top_texts: Optional[list[str]] = None


class SurveySummaryResponse(BaseModel):
    """Full descriptive analytics for one survey."""

    survey_id: str
    survey_title: str
    total_responses: int
    complete_responses: int
    partial_responses: int
    questions: list[QuestionSummary]


# ── Reliability Analysis ──────────────────────────────────────────────


class CronbachAlphaResult(BaseModel):
    """Cronbach's alpha for a group of Likert-scale items."""

    scale_name: str
    items: list[str]  # question names in this scale
    n_items: int
    n_valid_responses: int
    alpha: float  # raw Cronbach's α
    item_variances: dict[str, float]
    total_variance: float
    interpretation: str = Field(
        description="Human-readable interpretation: Poor (<0.6), "
        "Questionable (0.6-0.7), Acceptable (0.7-0.8), "
        "Good (0.8-0.9), Excellent (>0.9)"
    )


# ── Cross-Tabulation ──────────────────────────────────────────────────


class CrossTabResult(BaseModel):
    """Cross-tabulation of two categorical questions."""

    row_question: str
    col_question: str
    row_labels: list[str]
    col_labels: list[str]
    matrix: list[list[int]]  # row x col counts
    chi_square: Optional[float] = None
    cramers_v: Optional[float] = None
    n: int


# ── Response Quality ──────────────────────────────────────────────────


class ResponseQualityResult(BaseModel):
    """Data quality diagnostics for survey responses."""

    total_responses: int
    complete_responses: int
    completion_rate: float  # 0-100
    avg_completion_seconds: float
    median_completion_seconds: float
    # Speeders: completed faster than threshold (default < 1/3 median)
    speeder_count: int
    speeder_threshold_seconds: float
    # Straightliners: gave same answer for >= 80% of Likert items
    straightliner_count: int
    # Dropout analysis
    dropout_question: Optional[str] = Field(
        default=None, description="Question name where most dropouts occurred"
    )
    dropout_count: int = 0
