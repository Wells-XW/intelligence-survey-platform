"""Pydantic v2 schemas for survey response collection.

PIPL Compliance Note (Articles 18-24): The respondent metadata field
captures consent confirmation and anonymized IP (last octet zeroed).
Personal identifiers (name, phone, ID number) MUST NOT be stored in
the answers JSONB. See the platform's Data Minimization Policy.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SubmitResponseRequest(BaseModel):
    """Request body for submitting a survey response.

    No authentication required — surveys are publicly fillable.
    """

    answers: dict = Field(
        ..., description="{question_name → answer_value} mapping"
    )
    metadata: dict = Field(
        default_factory=dict,
        description=(
            "Must include 'pipl_consent': true (PIPL Art. 18). "
            "Optional: completion_time_seconds, user_agent"
        ),
    )
    respondent_id: Optional[str] = Field(
        default=None, max_length=320, description="Optional participant tracking ID"
    )
    is_complete: bool = Field(default=True)


class SurveyResponseOut(BaseModel):
    """Full response record returned to survey owners."""

    id: str
    survey_id: str
    respondent_id: Optional[str] = None
    answers: dict
    metadata: dict = Field(alias="metadata_json")
    is_complete: bool
    submitted_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class SurveyResponseListItem(BaseModel):
    """Abbreviated response for list views (no full answers)."""

    id: str
    survey_id: str
    respondent_id: Optional[str] = None
    is_complete: bool
    completion_time_seconds: Optional[float] = None
    submitted_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_row(cls, row) -> "SurveyResponseListItem":
        """Build from ORM, extracting completion_time from metadata."""
        return cls(
            id=row.id,
            survey_id=row.survey_id,
            respondent_id=row.respondent_id,
            is_complete=row.is_complete,
            completion_time_seconds=(
                row.metadata_json.get("completion_time_seconds")
                if row.metadata_json
                else None
            ),
            submitted_at=row.submitted_at,
        )
