"""KnowledgeScale ORM model — validated academic measurement scales library."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class KnowledgeScale(Base):
    """A validated academic measurement scale with reliability history."""

    __tablename__ = "knowledge_scales"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    discipline: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # psychology | sociology | education | management | health | other
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    items: Mapped[Optional[list]] = mapped_column(
        JSONB, nullable=True
    )  # [{code, text, reverse_scored}]
    cronbach_alpha: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cronbach_alpha_history: Mapped[Optional[list]] = mapped_column(
        JSONB, nullable=True
    )  # [{value, sample_n, year, citation}]
    citations: Mapped[Optional[list]] = mapped_column(
        JSONB, nullable=True
    )  # [{title, authors, year, doi}]
    language: Mapped[str] = mapped_column(String(10), default="zh")
    source_type: Mapped[str] = mapped_column(
        String(20), default="manual"
    )  # manual | api
    external_source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return (
            f"<KnowledgeScale(id={self.id}, name={self.name!r}, "
            f"discipline={self.discipline!r}, alpha={self.cronbach_alpha})>"
        )
