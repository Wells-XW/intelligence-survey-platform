"""Distribution ORM model — a distribution campaign for a sample group."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Distribution(Base):
    """A distribution campaign that sends a survey to a sample group.

    Workflow: draft → (send triggered) → sending → sent → completed.
    Counts (sent_count, opened_count, etc.) are denormalized for
    dashboard performance and updated on each status transition.
    """

    __tablename__ = "distributions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    survey_id: Mapped[str] = mapped_column(
        ForeignKey("surveys.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sample_group_id: Mapped[str] = mapped_column(
        ForeignKey("sample_groups.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    subject_template: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body_template: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="{text: '您好，诚邀参与...', link_label: '开始填写问卷'}",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        comment="draft | sending | sent | completed",
    )
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    opened_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    survey = relationship("Survey", back_populates="distributions")
    sample_group = relationship("SampleGroup")

    def __repr__(self) -> str:
        return (
            f"<Distribution(id={self.id}, name={self.name!r}, "
            f"status={self.status!r})>"
        )
