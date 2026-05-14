"""Recipient ORM model — individual survey recipient with tracking."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Recipient(Base):
    """A single recipient within a sample group.

    Each recipient gets a unique token that is embedded in the survey
    fill URL for per-recipient response tracking. Demographics (gender,
    age group, education, etc.) are stored as JSONB for quota matching.

    PIPL note: email and name are nullable. Demographics must not include
    ID numbers or precision-location data.
    """

    __tablename__ = "recipients"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    sample_group_id: Mapped[str] = mapped_column(
        ForeignKey("sample_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    external_id: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        index=True,
        comment="External ID for linking to pre-existing respondent databases",
    )
    demographics: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Demographic attributes for quota matching, e.g. {gender: '男', age_group: '25-34'}",
    )
    unique_token: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        default=lambda: uuid.uuid4().hex,
        comment="Unique token for personal survey fill link; 32 hex chars",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        comment="pending | sent | opened | started | completed | bounced | opted_out",
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    opened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    sample_group = relationship("SampleGroup", back_populates="recipients")

    def __repr__(self) -> str:
        return (
            f"<Recipient(id={self.id}, status={self.status!r}, "
            f"group={self.sample_group_id[:8]}...)>"
        )
