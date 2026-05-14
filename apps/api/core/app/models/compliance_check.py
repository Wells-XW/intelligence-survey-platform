"""ComplianceCheck ORM model — ethics & regulatory compliance audit records."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class ComplianceCheck(Base):
    """Records the result of a single compliance check against a survey.

    Supports both automated rule-based checks and AI-assisted reviews.
    Each check targets a specific compliance dimension (PIPL, GDPR, bias,
    sensitive info, consent, data minimization) and produces findings
    with risk levels and actionable suggestions.

    Immutable — checks are never updated, only appended as new versions.
    """

    __tablename__ = "compliance_checks"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    survey_id: Mapped[str] = mapped_column(
        ForeignKey("surveys.id", ondelete="CASCADE"), nullable=False, index=True
    )
    check_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # pipl_baseline | gdpr_baseline | bias_scan | sensitive_info |
    # consent_verification | data_minimization | full_scan | ai_review
    status: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # pass | fail | warning
    risk_level: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # low | medium | high | critical

    # Structured findings: list of {dimension, issue, severity, evidence}
    findings: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Actionable suggestions: list of {priority, title, description, reference}
    suggestions: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Aggregate risk score (0–100)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Number of items checked
    items_checked: Mapped[int] = mapped_column(Integer, default=0)
    items_passed: Mapped[int] = mapped_column(Integer, default=0)
    items_warning: Mapped[int] = mapped_column(Integer, default=0)
    items_failed: Mapped[int] = mapped_column(Integer, default=0)

    # Who initiated the check
    checked_by: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    # Relation
    survey = relationship("Survey")
    user = relationship("User")

    def __repr__(self) -> str:
        return (
            f"<ComplianceCheck(survey_id={self.survey_id}, "
            f"type={self.check_type!r}, risk={self.risk_level!r}, "
            f"score={self.risk_score:.0f})>"
        )
