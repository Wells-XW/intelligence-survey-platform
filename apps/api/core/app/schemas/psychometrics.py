"""Psychometrics schemas for Measurement Toolkit API."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Split-Half ──────────────────────────────────────────────────────────


class SplitHalfResult(BaseModel):
    """Split-half reliability with Spearman-Brown correction."""

    spearman_brown: Optional[float] = Field(
        description="Spearman-Brown corrected reliability coefficient"
    )
    split_half_r: Optional[float] = Field(
        description="Pearson correlation between half-scores"
    )
    method: str = Field(description="Split method: odd_even or first_second")
    half1_items: list[str] = Field(description="Items in first half")
    half2_items: list[str] = Field(description="Items in second half")
    n_valid: int = Field(description="Number of complete-case respondents")
    interpretation: str = Field(description="Human-readable interpretation label")
    error: Optional[str] = Field(default=None, description="Error code if computation failed")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "spearman_brown": 0.81,
                    "split_half_r": 0.68,
                    "method": "odd_even",
                    "half1_items": ["q1", "q3", "q5"],
                    "half2_items": ["q2", "q4", "q6"],
                    "n_valid": 280,
                    "interpretation": "Good (0.8-0.9)",
                    "error": None,
                }
            ]
        }
    )


# ── Item-Total ──────────────────────────────────────────────────────────


class ItemTotalItem(BaseModel):
    """Single item in the item-total correlation analysis."""

    item_name: str
    corrected_item_total_r: float
    alpha_if_deleted: Optional[float] = None
    flag: str = Field(description="Quality flag: good, moderate, or weak")


class ItemTotalCorrelationResult(BaseModel):
    """Corrected item-total correlations for a set of items."""

    items: list[ItemTotalItem]
    n_valid: int
    error: Optional[str] = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "item_name": "q1",
                            "corrected_item_total_r": 0.62,
                            "alpha_if_deleted": 0.81,
                            "flag": "good",
                        },
                        {
                            "item_name": "q5",
                            "corrected_item_total_r": 0.18,
                            "alpha_if_deleted": 0.86,
                            "flag": "weak",
                        },
                    ],
                    "n_valid": 280,
                    "error": None,
                }
            ]
        }
    )


# ── KMO & Bartlett ─────────────────────────────────────────────────────


class KmoBartlettResult(BaseModel):
    """KMO sampling adequacy and Bartlett's test of sphericity."""

    kmo_overall: Optional[float] = Field(
        description="Overall Kaiser-Meyer-Olkin measure"
    )
    kmo_per_item: dict[str, float] = Field(
        description="Per-item KMO values keyed by item name"
    )
    bartlett_chi_square: Optional[float] = Field(
        description="Bartlett's chi-square statistic"
    )
    bartlett_df: Optional[int] = Field(
        description="Degrees of freedom for Bartlett's test"
    )
    bartlett_p_value: Optional[float] = Field(
        description="P-value for Bartlett's test"
    )
    n_valid: int
    interpretation: str
    error: Optional[str] = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "kmo_overall": 0.81,
                    "kmo_per_item": {"q1": 0.83, "q2": 0.78, "q3": 0.82},
                    "bartlett_chi_square": 412.7,
                    "bartlett_df": 10,
                    "bartlett_p_value": 0.0,
                    "n_valid": 280,
                    "interpretation": "Meritorious (KMO ≥ 0.8)",
                    "error": None,
                }
            ]
        }
    )


# ── Construct Psychometrics ────────────────────────────────────────────


class ConstructDefinition(BaseModel):
    """Definition of a measurement construct (latent variable)."""

    name: str = Field(description="Construct/latent variable name")
    items: list[str] = Field(description="Item question names belonging to this construct")


class ConstructPsychometric(BaseModel):
    """Psychometric results for a single construct."""

    name: str
    n_items: int
    n_valid: int
    cronbach_alpha: Optional[float] = None
    alpha_interpretation: str = "N/A"
    split_half: Optional[float] = None
    item_total: list[ItemTotalItem] = Field(default_factory=list)


class InterConstructCorrelation(BaseModel):
    """Pairwise correlation between two constructs."""

    construct_a: str
    construct_b: str
    correlation: Optional[float] = None


class ConstructPsychometricsResult(BaseModel):
    """Multi-construct psychometrics analysis result."""

    constructs: list[ConstructPsychometric]
    inter_correlations: list[InterConstructCorrelation]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "constructs": [
                        {
                            "name": "学术诚信认知",
                            "n_items": 4,
                            "n_valid": 280,
                            "cronbach_alpha": 0.83,
                            "alpha_interpretation": "Good (0.8-0.9)",
                            "split_half": 0.78,
                            "item_total": [],
                        }
                    ],
                    "inter_correlations": [
                        {
                            "construct_a": "学术诚信认知",
                            "construct_b": "导师指导满意度",
                            "correlation": 0.42,
                        }
                    ],
                }
            ]
        }
    )


class ConstructPsychometricsRequest(BaseModel):
    """Request body for construct psychometrics analysis."""

    constructs: list[ConstructDefinition] = Field(
        description="List of construct definitions with their items"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "constructs": [
                        {
                            "name": "学术诚信认知",
                            "items": ["q1", "q2", "q3", "q4"],
                        },
                        {
                            "name": "导师指导满意度",
                            "items": ["q5", "q6", "q7"],
                        },
                    ]
                }
            ]
        }
    )


# ── Psychometric Report ────────────────────────────────────────────────


class ReportSection(BaseModel):
    """A section in the psychometric report."""

    title: str = Field(description="Section title")
    type: str = Field(description="Section type: text, table, metric_card, comparison_table")
    content: dict = Field(description="Structured section content")


class PsychometricReportResponse(BaseModel):
    """APA-style comprehensive psychometric report."""

    survey_id: str
    survey_title: str
    sections: list[ReportSection] = Field(default_factory=list)
    generated_at: str = Field(description="ISO 8601 timestamp")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                    "survey_title": "学术诚信认知调查（2026春）",
                    "sections": [
                        {
                            "title": "信度",
                            "type": "metric_card",
                            "content": {
                                "alpha": 0.83,
                                "interpretation": "Good",
                            },
                        }
                    ],
                    "generated_at": "2026-09-15T10:23:00Z",
                }
            ]
        }
    )


# ── Reliability Norm Comparison ────────────────────────────────────────


class ScaleNormEntry(BaseModel):
    """Comparison entry between observed and published scale reliability."""

    scale_id: str
    scale_name: str
    discipline: Optional[str] = None
    published_alpha: float
    observed_alpha: float
    difference: float = Field(description="published_alpha - observed_alpha")
    n_published: Optional[int] = None
    citation: Optional[str] = None


class ReliabilityNormComparisonResult(BaseModel):
    """Comparison of observed reliability against published scale norms."""

    observed_alpha: float
    n_items: int
    n_valid: int
    comparison_scales: list[ScaleNormEntry]
    summary: str

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "observed_alpha": 0.83,
                    "n_items": 5,
                    "n_valid": 280,
                    "comparison_scales": [
                        {
                            "scale_id": "scale_aci_zh_2019",
                            "scale_name": "学术诚信简表-中文版",
                            "discipline": "教育学",
                            "published_alpha": 0.86,
                            "observed_alpha": 0.83,
                            "difference": 0.03,
                            "n_published": 612,
                            "citation": "Wang & Liu (2019)",
                        }
                    ],
                    "summary": "观测信度低于公开常模 0.03，处于可接受范围。",
                }
            ]
        }
    )
