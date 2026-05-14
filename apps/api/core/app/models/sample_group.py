"""SampleGroup ORM model — a named group of recipients for a survey."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class SampleGroup(Base):
    """A named collection of recipients for survey distribution.

    Each survey can have multiple sample groups (e.g., "心理学系大一学生",
    "30-45岁在职人群"). Recipients within a group are managed via the
    Recipient model.
    """

    __tablename__ = "sample_groups"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    survey_id: Mapped[str] = mapped_column(
        ForeignKey("surveys.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recipient_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    survey = relationship("Survey", back_populates="sample_groups")
    recipients = relationship(
        "Recipient", back_populates="sample_group", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<SampleGroup(id={self.id}, name={self.name!r}, "
            f"count={self.recipient_count})>"
        )
