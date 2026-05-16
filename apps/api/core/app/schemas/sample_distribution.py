"""Pydantic v2 schemas for sample distribution management.

Organized in four sections mirroring the data models:
SampleGroup, Recipient, Distribution, Quota, plus Dashboard aggregation.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ══════════════════════════════════════════════════════════════════════════
# Sample Group
# ══════════════════════════════════════════════════════════════════════════


class CreateSampleGroupRequest(BaseModel):
    name: str = Field(..., max_length=200, description="Sample group display name")
    description: Optional[str] = Field(default=None, description="Optional notes")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "Pilot 第一轮（硕博）",
                    "description": "针对清北复交 2024 入学硕博样本",
                }
            ]
        }
    )


class UpdateSampleGroupRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"name": "Pilot 第一轮（硕博・终版）"}]
        }
    )


_SAMPLE_GROUP_RESPONSE_EXAMPLE = {
    "id": "f3b9f1e6-c2a4-4d2c-8a11-d3b07384d9a8",
    "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
    "name": "Pilot 第一轮（硕博）",
    "description": "针对清北复交 2024 入学硕博样本",
    "recipient_count": 240,
    "created_at": "2026-09-01T08:00:00Z",
    "updated_at": "2026-09-15T10:23:00Z",
}


class SampleGroupResponse(BaseModel):
    id: str
    survey_id: str
    name: str
    description: Optional[str] = None
    recipient_count: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [_SAMPLE_GROUP_RESPONSE_EXAMPLE]},
    )


class SampleGroupListItem(BaseModel):
    id: str
    name: str
    recipient_count: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": _SAMPLE_GROUP_RESPONSE_EXAMPLE["id"],
                    "name": _SAMPLE_GROUP_RESPONSE_EXAMPLE["name"],
                    "recipient_count": _SAMPLE_GROUP_RESPONSE_EXAMPLE[
                        "recipient_count"
                    ],
                    "created_at": _SAMPLE_GROUP_RESPONSE_EXAMPLE["created_at"],
                    "updated_at": _SAMPLE_GROUP_RESPONSE_EXAMPLE["updated_at"],
                }
            ]
        },
    )


# ══════════════════════════════════════════════════════════════════════════
# Recipient
# ══════════════════════════════════════════════════════════════════════════


class CreateRecipientRequest(BaseModel):
    email: Optional[str] = Field(default=None, max_length=320)
    name: Optional[str] = Field(default=None, max_length=200)
    external_id: Optional[str] = Field(default=None, max_length=200)
    demographics: dict = Field(default_factory=dict)

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "email": "respondent.0042@example.edu",
                    "name": "张瑞",
                    "external_id": "univ-id-2024-0042",
                    "demographics": {
                        "gender": "女",
                        "discipline": "社会学",
                        "year": "硕一",
                    },
                }
            ]
        }
    )


class UpdateRecipientRequest(BaseModel):
    email: Optional[str] = Field(default=None, max_length=320)
    name: Optional[str] = Field(default=None, max_length=200)
    demographics: Optional[dict] = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "demographics": {
                        "gender": "女",
                        "discipline": "社会学",
                        "year": "硕二",
                    }
                }
            ]
        }
    )


_RECIPIENT_RESPONSE_EXAMPLE = {
    "id": "8a11d3b0-7384-4d9a-83b0-d9a84f3b9f1e",
    "sample_group_id": "f3b9f1e6-c2a4-4d2c-8a11-d3b07384d9a8",
    "email": "respondent.0042@example.edu",
    "name": "张瑞",
    "external_id": "univ-id-2024-0042",
    "demographics": {
        "gender": "女",
        "discipline": "社会学",
        "year": "硕一",
    },
    "unique_token": "Y3lwR0szbW1xdWZUcXJZdF9YYUJUVmRyV3lqM3lEbzU",
    "status": "completed",
    "sent_at": "2026-09-10T08:00:00Z",
    "opened_at": "2026-09-10T09:14:00Z",
    "completed_at": "2026-09-10T09:21:30Z",
    "created_at": "2026-09-01T08:00:00Z",
}


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

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [_RECIPIENT_RESPONSE_EXAMPLE]},
    )


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

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": _RECIPIENT_RESPONSE_EXAMPLE["id"],
                    "email": _RECIPIENT_RESPONSE_EXAMPLE["email"],
                    "name": _RECIPIENT_RESPONSE_EXAMPLE["name"],
                    "demographics": _RECIPIENT_RESPONSE_EXAMPLE["demographics"],
                    "status": _RECIPIENT_RESPONSE_EXAMPLE["status"],
                    "sent_at": _RECIPIENT_RESPONSE_EXAMPLE["sent_at"],
                    "completed_at": _RECIPIENT_RESPONSE_EXAMPLE["completed_at"],
                    "created_at": _RECIPIENT_RESPONSE_EXAMPLE["created_at"],
                }
            ]
        },
    )


class RecipientImportResult(BaseModel):
    imported: int
    skipped: int
    errors: list[str] = Field(default_factory=list)

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "imported": 240,
                    "skipped": 3,
                    "errors": [
                        "Row 17: missing email column",
                        "Row 24: invalid email format",
                    ],
                }
            ]
        }
    )


# ══════════════════════════════════════════════════════════════════════════
# Distribution
# ══════════════════════════════════════════════════════════════════════════


class CreateDistributionRequest(BaseModel):
    sample_group_id: str
    name: str = Field(..., max_length=200)
    subject_template: Optional[str] = None
    body_template: dict = Field(default_factory=dict)
    scheduled_at: Optional[datetime] = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "sample_group_id": "f3b9f1e6-c2a4-4d2c-8a11-d3b07384d9a8",
                    "name": "Pilot 第一轮 · 邀请邮件",
                    "subject_template": "邀请参与学术诚信调查（2026春）",
                    "body_template": {
                        "greeting": "您好 {{name}}，",
                        "body": "诚邀参加由{{owner}}主持的研究调查",
                        "cta": "点击此处填写问卷",
                    },
                    "scheduled_at": "2026-09-20T08:00:00Z",
                }
            ]
        }
    )


class UpdateDistributionRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    subject_template: Optional[str] = None
    body_template: Optional[dict] = None
    scheduled_at: Optional[datetime] = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"scheduled_at": "2026-09-21T08:00:00Z"}
            ]
        }
    )


_DISTRIBUTION_RESPONSE_EXAMPLE = {
    "id": "1e6c2a4d-2c8a-411d-b073-84d9a84f3b9f",
    "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
    "sample_group_id": "f3b9f1e6-c2a4-4d2c-8a11-d3b07384d9a8",
    "name": "Pilot 第一轮 · 邀请邮件",
    "subject_template": "邀请参与学术诚信调查（2026春）",
    "body_template": {
        "greeting": "您好 {{name}}，",
        "body": "诚邀参加由{{owner}}主持的研究调查",
        "cta": "点击此处填写问卷",
    },
    "status": "sent",
    "sent_count": 240,
    "opened_count": 187,
    "started_count": 162,
    "completed_count": 138,
    "scheduled_at": "2026-09-20T08:00:00Z",
    "created_at": "2026-09-15T10:23:00Z",
    "updated_at": "2026-09-20T08:01:30Z",
}


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

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [_DISTRIBUTION_RESPONSE_EXAMPLE]},
    )


class DistributionListItem(BaseModel):
    id: str
    name: str
    status: str
    sample_group_name: Optional[str] = None
    sent_count: int
    completed_count: int
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": _DISTRIBUTION_RESPONSE_EXAMPLE["id"],
                    "name": _DISTRIBUTION_RESPONSE_EXAMPLE["name"],
                    "status": _DISTRIBUTION_RESPONSE_EXAMPLE["status"],
                    "sample_group_name": "Pilot 第一轮（硕博）",
                    "sent_count": _DISTRIBUTION_RESPONSE_EXAMPLE["sent_count"],
                    "completed_count": _DISTRIBUTION_RESPONSE_EXAMPLE[
                        "completed_count"
                    ],
                    "created_at": _DISTRIBUTION_RESPONSE_EXAMPLE["created_at"],
                }
            ]
        },
    )


class SendDistributionResponse(BaseModel):
    distribution_id: str
    recipients_processed: int
    links_generated: int

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "distribution_id": "1e6c2a4d-2c8a-411d-b073-84d9a84f3b9f",
                    "recipients_processed": 240,
                    "links_generated": 240,
                }
            ]
        }
    )


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

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "女性硕士配额",
                    "dimension": "gender_x_degree",
                    "target_count": 80,
                    "criteria": {"gender": "女", "degree": "硕士"},
                }
            ]
        }
    )


class UpdateQuotaRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    target_count: Optional[int] = Field(default=None, gt=0)
    criteria: Optional[dict] = None
    is_active: Optional[bool] = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"target_count": 100, "is_active": True}]
        }
    )


_QUOTA_RESPONSE_EXAMPLE = {
    "id": "c2a44d2c-8a11-4d3b-9f1e-7384d9a84f3b",
    "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
    "name": "女性硕士配额",
    "dimension": "gender_x_degree",
    "target_count": 80,
    "current_count": 47,
    "criteria": {"gender": "女", "degree": "硕士"},
    "is_active": True,
    "fill_rate": 58.8,
    "created_at": "2026-09-01T08:00:00Z",
    "updated_at": "2026-09-20T15:30:00Z",
}


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

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [_QUOTA_RESPONSE_EXAMPLE]},
    )


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

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                    "survey_title": "学术诚信认知调查（2026春）",
                    "total_recipients": 480,
                    "total_responded": 312,
                    "response_rate": 65.0,
                    "total_distributions": 3,
                    "active_distributions": 1,
                    "quotas": [_QUOTA_RESPONSE_EXAMPLE],
                    "sample_groups": [_SAMPLE_GROUP_RESPONSE_EXAMPLE],
                }
            ]
        }
    )
