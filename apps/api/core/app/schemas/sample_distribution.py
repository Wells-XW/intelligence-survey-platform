"""Pydantic v2 schemas for sample distribution management.

Organized in four sections mirroring the data models:
SampleGroup, Recipient, Distribution, Quota, plus Dashboard aggregation.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════════════════════
# Sample Group
# ══════════════════════════════════════════════════════════════════════════


class CreateSampleGroupRequest(BaseModel):
    name: str = Field(..., max_length=200, description="Sample group display name")
    description: Optional[str] = Field(default=None, description="Optional notes")


class UpdateSampleGroupRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None


class SampleGroupResponse(BaseModel):
    id: str
    survey_id: str
    name: str
    description: Optional[str] = None
    recipient_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SampleGroupListItem(BaseModel):
    id: str
    name: str
    recipient_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ══════════════════════════════════════════════════════════════════════════
# Recipient
# ══════════════════════════════════════════════════════════════════════════


class CreateRecipientRequest(BaseModel):
    email: Optional[str] = Field(default=None, max_length=320)
    name: Optional[str] = Field(default=None, max_length=200)
    external_id: Optional[str] = Field(default=None, max_length=200)
    demographics: dict = Field(default_factory=dict)


class UpdateRecipientRequest(BaseModel):
    email: Optional[str] = Field(default=None, max_length=320)
    name: Optional[str] = Field(default=None, max_length=200)
    demographics: Optional[dict] = None


class RecipientResponse(BaseModel):
    """Full recipient detail — unique_token is included for editors/owners."""

    id: str
    sample_group_id: str
    email: Optional[str] = None
    name: Optional[str] = None
    external_id: Optional[str] = None
    demographics: dict
    unique_token: str
    status: str
    sent_at: Optional[datetime] = None
    opened_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class RecipientListItem(BaseModel):
    """Abbreviated recipient for list views — no unique_token exposed."""

    id: str
    email: Optional[str] = None
    name: Optional[str] = None
    demographics: dict
    status: str
    sent_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class RecipientImportResult(BaseModel):
    imported: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════
# Distribution
# ══════════════════════════════════════════════════════════════════════════


class CreateDistributionRequest(BaseModel):
    sample_group_id: str
    name: str = Field(..., max_length=200)
    subject_template: Optional[str] = None
    body_template: dict = Field(default_factory=dict)
    scheduled_at: Optional[datetime] = None


class UpdateDistributionRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    subject_template: Optional[str] = None
    body_template: Optional[dict] = None
    scheduled_at: Optional[datetime] = None


class DistributionResponse(BaseModel):
    id: str
    survey_id: str
    sample_group_id: str
    name: str
    subject_template: Optional[str] = None
    body_template: dict
    status: str
    sent_count: int
    opened_count: int
    started_count: int
    completed_count: int
    scheduled_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DistributionListItem(BaseModel):
    id: str
    name: str
    status: str
    sample_group_name: Optional[str] = None
    sent_count: int
    completed_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class SendDistributionResponse(BaseModel):
    distribution_id: str
    recipients_processed: int
    links_generated: int


# ══════════════════════════════════════════════════════════════════════════
# Quota
# ══════════════════════════════════════════════════════════════════════════


class CreateQuotaRequest(BaseModel):
    name: str = Field(..., max_length=200)
    dimension: str = Field(..., max_length=50, description="e.g. 'gender', 'age_group'")
    target_count: int = Field(..., gt=0, description="Target number of responses")
    criteria: dict = Field(
        ..., description="Key-value pairs to match, e.g. {'gender': '男'}"
    )


class UpdateQuotaRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    target_count: Optional[int] = Field(default=None, gt=0)
    criteria: Optional[dict] = None
    is_active: Optional[bool] = None


class QuotaResponse(BaseModel):
    id: str
    survey_id: str
    name: str
    dimension: str
    target_count: int
    current_count: int
    criteria: dict
    is_active: bool
    fill_rate: float = Field(description="current_count / target_count * 100, rounded to 1 decimal")
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ══════════════════════════════════════════════════════════════════════════
# Dashboard Aggregate
# ══════════════════════════════════════════════════════════════════════════


class DistributionDashboardResponse(BaseModel):
    survey_id: str
    survey_title: str
    total_recipients: int
    total_responded: int
    response_rate: float = Field(description="total_responded / total_recipients * 100")
    total_distributions: int
    active_distributions: int
    quotas: list[QuotaResponse]
    sample_groups: list[SampleGroupResponse]
