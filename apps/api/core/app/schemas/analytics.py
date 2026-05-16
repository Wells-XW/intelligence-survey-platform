"""Pydantic v2 schemas for survey analytics responses."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


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

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                    "survey_title": "学术诚信认知调查（2026春）",
                    "total_responses": 312,
                    "complete_responses": 287,
                    "partial_responses": 25,
                    "questions": [
                        {
                            "question_name": "q1",
                            "question_text": "整体而言，您对当前学术诚信制度的满意度如何？",
                            "question_type": "rating",
                            "total_answers": 287,
                            "skipped": 0,
                            "numeric_stats": {
                                "mean": 3.42,
                                "median": 3.0,
                                "mode": [4.0],
                                "std_dev": 0.91,
                                "min_value": 1.0,
                                "max_value": 5.0,
                                "n": 287,
                            },
                        }
                    ],
                }
            ]
        }
    )


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

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "scale_name": "学术诚信认知（5题）",
                    "items": ["q1", "q2", "q3", "q4", "q5"],
                    "n_items": 5,
                    "n_valid_responses": 280,
                    "alpha": 0.83,
                    "item_variances": {
                        "q1": 0.84,
                        "q2": 0.91,
                        "q3": 0.78,
                        "q4": 0.95,
                        "q5": 0.88,
                    },
                    "total_variance": 12.4,
                    "interpretation": "Good (0.8-0.9)",
                }
            ]
        }
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

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "row_question": "gender",
                    "col_question": "agree_with_policy",
                    "row_labels": ["女", "男", "其他"],
                    "col_labels": ["同意", "中立", "不同意"],
                    "matrix": [[58, 22, 14], [44, 31, 19], [3, 1, 0]],
                    "chi_square": 5.71,
                    "cramers_v": 0.13,
                    "n": 192,
                }
            ]
        }
    )


# ── Response Quality ──────────────────────────────────────────────────


class ResponseQualityResult(BaseModel):
    """Data quality diagnostics for survey responses.

    Includes basic quality metrics (completion rate, speeders,
    straightliners) and extended T9 metrics (missing patterns,
    inconsistency detection, response time distribution, and
    attention check performance).
    """

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
    # T9 extended metrics
    missing_patterns: Optional[dict] = Field(
        default=None,
        description="Missing pattern analysis: per-item rates, co-missing pairs, distribution",
    )
    inconsistency_rate: Optional[float] = Field(
        default=None,
        description="Rate of respondents with inconsistency between forward and reverse-coded items",
    )
    inconsistent_respondents: Optional[int] = Field(
        default=None,
        description="Number of respondents with response inconsistencies",
    )
    response_time_distribution: Optional[dict] = Field(
        default=None,
        description="Response time quantiles (P5/P25/P50/P75/P95)",
    )
    attention_check_pass_rate: Optional[float] = Field(
        default=None,
        description="Percentage of attention checks passed (0-100)",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "total_responses": 312,
                    "complete_responses": 287,
                    "completion_rate": 91.99,
                    "avg_completion_seconds": 184.3,
                    "median_completion_seconds": 162.5,
                    "speeder_count": 11,
                    "speeder_threshold_seconds": 54.2,
                    "straightliner_count": 7,
                    "dropout_question": "q14",
                    "dropout_count": 18,
                    "missing_patterns": {
                        "per_item_rate": {"q3": 0.04, "q14": 0.18},
                        "co_missing": [["q12", "q13"]],
                    },
                    "inconsistency_rate": 3.5,
                    "inconsistent_respondents": 11,
                    "response_time_distribution": {
                        "p5": 62.0,
                        "p25": 132.0,
                        "p50": 162.5,
                        "p75": 218.0,
                        "p95": 401.0,
                    },
                    "attention_check_pass_rate": 96.4,
                }
            ]
        }
    )
