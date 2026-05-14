"""SurveyResponse ORM model.

Stores respondent answers as flexible JSONB to support any SurveyJS
question type without schema changes. Supports both authenticated and
anonymous respondents (PIPL Art. 18-24 compliant).
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class SurveyResponse(Base):
    """A single respondent's complete answers for a survey."""

    __tablename__ = "survey_responses"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    survey_id: Mapped[str] = mapped_column(
        ForeignKey("surveys.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Optional: link to registered user; NULL for anonymous respondents
    respondent_id: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True, index=True
    )
    # answers: {question_name: answer_value} mapping
    # Supports all SurveyJS types: text, number, boolean, rating, ranking,
    # matrix, multipletext, dropdown, checkbox, radiogroup, etc.
    answers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Metadata for data quality & PIPL compliance
    #   pipL_consent: bool — respondent confirmed privacy notice
    #   completion_time_seconds: float — time from start to submit
    #   user_agent: str — browser identifier
    #   ip_address: str — anonymized (last octet zeroed for PIPL)
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    is_complete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    survey = relationship("Survey", back_populates="responses")

    def __repr__(self) -> str:
        return (
            f"<SurveyResponse(id={self.id}, survey_id={self.survey_id!r}, "
            f"submitted_at={self.submitted_at.isoformat()!r})>"
        )
