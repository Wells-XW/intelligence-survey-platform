"""Psychometrics schemas for Measurement Toolkit API."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


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


class ConstructPsychometricsRequest(BaseModel):
    """Request body for construct psychometrics analysis."""

    constructs: list[ConstructDefinition] = Field(
        description="List of construct definitions with their items"
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
