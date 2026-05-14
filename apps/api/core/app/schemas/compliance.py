"""Pydantic v2 schemas for compliance check API responses."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── Compliance Check ────────────────────────────────────────────────────


class ComplianceFinding(BaseModel):
    """A single compliance finding."""

    dimension: str  # pipl | gdpr | bias | sensitive_info | consent | minimization
    issue: str  # Human-readable description of the issue
    severity: str = "info"  # info | warning | error
    evidence: Optional[str] = None  # Quote from survey that triggered the finding
    reference: Optional[str] = None  # Legal/standards reference (e.g., "PIPL Art.14")


class ComplianceSuggestion(BaseModel):
    """An actionable suggestion to fix a compliance issue."""

    priority: str = "medium"  # low | medium | high | critical
    title: str
    description: str
    reference: Optional[str] = None


class ComplianceCheckResponse(BaseModel):
    """API response for a single compliance check."""

    id: str
    survey_id: str
    check_type: str
    status: str  # pass | fail | warning
    risk_level: str  # low | medium | high | critical
    risk_score: float  # 0–100
    findings: list[ComplianceFinding] = Field(default_factory=list)
    suggestions: list[ComplianceSuggestion] = Field(default_factory=list)
    items_checked: int = 0
    items_passed: int = 0
    items_warning: int = 0
    items_failed: int = 0
    checked_at: datetime


class ComplianceScanRequest(BaseModel):
    """Request to run a compliance scan.

    By default (check_types empty), runs all available checks.
    """

    check_types: Optional[list[str]] = Field(
        default=None,
        description="Specific check types to run. Empty = all.",
    )
    include_ai_review: bool = Field(
        default=False,
        description="If true, also runs an AI-assisted deep review after rule-based checks.",
    )


class AiReviewRequest(BaseModel):
    """Request for AI-assisted compliance review."""

    focus_areas: Optional[list[str]] = Field(
        default=None,
        description="Specific areas for AI to focus on (pipl, gdpr, bias, sensitive, etc.)",
    )
    include_open_ended: bool = Field(
        default=True,
        description="Whether to analyze open-ended questions for indirect sensitive info collection.",
    )


class ComplianceHistoryResponse(BaseModel):
    """List of past compliance checks for a survey."""

    survey_id: str
    checks: list[ComplianceCheckResponse] = Field(default_factory=list)
    latest_risk_score: Optional[float] = None
    latest_risk_level: Optional[str] = None
    total_checks: int = 0


class ComplianceReportResponse(BaseModel):
    """Full compliance report in Markdown format."""

    survey_id: str
    survey_title: str
    report_markdown: str
    risk_score: float
    risk_level: str
    generated_at: datetime
