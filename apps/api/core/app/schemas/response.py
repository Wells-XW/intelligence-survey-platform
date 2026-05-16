"""Pydantic v2 schemas for survey response collection.

PIPL Compliance Note (Articles 18-24): The respondent metadata field
captures consent confirmation and anonymized IP (last octet zeroed).
Personal identifiers (name, phone, ID number) MUST NOT be stored in
the answers JSONB. See the platform's Data Minimization Policy.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


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

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "answers": {"q1": 4, "q2": "非常符合", "q3": ["a", "c"]},
                    "metadata": {
                        "pipl_consent": True,
                        "completion_time_seconds": 142.5,
                    },
                    "respondent_id": "recipient_38291",
                    "is_complete": True,
                }
            ]
        }
    )


class SurveyResponseOut(BaseModel):
    """Full response record returned to survey owners."""

    id: str
    survey_id: str
    respondent_id: Optional[str] = None
    answers: dict
    metadata: dict = Field(alias="metadata_json")
    is_complete: bool
    submitted_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "8a11d3b0-7384-4d9a-83b0-d9a84f3b9f1e",
                    "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                    "respondent_id": "recipient_38291",
                    "answers": {"q1": 4, "q2": "非常符合", "q3": ["a", "c"]},
                    "metadata": {
                        "pipl_consent": True,
                        "completion_time_seconds": 142.5,
                        "ip_address": "198.51.100.0",
                        "user_agent": "Mozilla/5.0",
                    },
                    "is_complete": True,
                    "submitted_at": "2026-09-15T10:23:00Z",
                }
            ]
        },
    )


class SurveyResponseListItem(BaseModel):
    """Abbreviated response for list views (no full answers)."""

    id: str
    survey_id: str
    respondent_id: Optional[str] = None
    is_complete: bool
    completion_time_seconds: Optional[float] = None
    submitted_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "8a11d3b0-7384-4d9a-83b0-d9a84f3b9f1e",
                    "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                    "respondent_id": "recipient_38291",
                    "is_complete": True,
                    "completion_time_seconds": 142.5,
                    "submitted_at": "2026-09-15T10:23:00Z",
                }
            ]
        },
    )

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
