"""Pydantic v2 schemas for compliance check API responses."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


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

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "c2a44d2c-8a11-4d3b-9f1e-7384d9a84f3b",
                    "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                    "check_type": "full_scan",
                    "status": "warning",
                    "risk_level": "medium",
                    "risk_score": 42.5,
                    "findings": [
                        {
                            "dimension": "pipl",
                            "issue": "缺少明确的知情同意提示文字",
                            "severity": "warning",
                            "evidence": "首页未显示 pipl_consent 勾选项",
                            "reference": "PIPL Art.14",
                        }
                    ],
                    "suggestions": [
                        {
                            "priority": "high",
                            "title": "在问卷首页添加知情同意勾选",
                            "description": "在 pages[0] 顶部增加 pipl_consent 必填项",
                            "reference": "PIPL Art.14",
                        }
                    ],
                    "items_checked": 18,
                    "items_passed": 14,
                    "items_warning": 4,
                    "items_failed": 0,
                    "checked_at": "2026-09-15T10:23:00Z",
                }
            ]
        }
    )


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

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "check_types": ["pipl", "consent", "minimization"],
                    "include_ai_review": True,
                }
            ]
        }
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

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                    "checks": [],
                    "latest_risk_score": 42.5,
                    "latest_risk_level": "medium",
                    "total_checks": 4,
                }
            ]
        }
    )


class ComplianceReportResponse(BaseModel):
    """Full compliance report in Markdown format."""

    survey_id: str
    survey_title: str
    report_markdown: str
    risk_score: float
    risk_level: str
    generated_at: datetime

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                    "survey_title": "学术诚信认知调查（2026春）",
                    "report_markdown": (
                        "# 伦理合规审查报告\n\n"
                        "**风险等级**: MEDIUM (42.5/100)\n\n"
                        "## PIPL 合规\n- ⚠️ 缺少明确的知情同意提示文字\n"
                    ),
                    "risk_score": 42.5,
                    "risk_level": "medium",
                    "generated_at": "2026-09-15T10:23:00Z",
                }
            ]
        }
    )
