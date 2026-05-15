"""SurveyVersion ORM model — immutable JSONB snapshots of survey content."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class SurveyVersion(Base):
    """Immutable snapshot of a survey at a specific version number.

    Created automatically whenever a survey is saved (PUT).  Each
    snapshot captures the full survey JSON content so that a previous
    version can be restored with a single click.
    """

    __tablename__ = "survey_versions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    survey_id: Mapped[str] = mapped_column(
        ForeignKey("surveys.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    json_content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    creator_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    changelog: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    survey = relationship("Survey", back_populates="versions")
    creator = relationship("User", foreign_keys=[creator_id])

    __table_args__ = (
        UniqueConstraint("survey_id", "version", name="uq_survey_version_number"),
    )

    def __repr__(self) -> str:
        return (
            f"<SurveyVersion(id={self.id}, survey={self.survey_id!r}, "
            f"version={self.version})>"
        )
