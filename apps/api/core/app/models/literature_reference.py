"""LiteratureReference ORM model — saved academic paper references."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class LiteratureReference(Base):
    """A saved academic paper reference for a user."""

    __tablename__ = "literature_references"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_source: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # pubmed | semantic_scholar | cnki_web | manual
    external_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    authors: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    journal: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    abstract: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    doi: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, index=True)
    url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    keywords: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    raw_citation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_saved: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "external_source",
            "external_id",
            name="uq_lit_ref_user_source_ext",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<LiteratureReference(id={self.id}, "
            f"source={self.external_source!r}, "
            f"title={self.title[:60]!r})>"
        )
