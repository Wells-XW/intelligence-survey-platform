"""KnowledgeEntry ORM model — methodology guides, best practices, templates."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class KnowledgeEntry(Base):
    """A methodological guide, best practice, or template entry."""

    __tablename__ = "knowledge_entries"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # methodology_guide | best_practice | template | glossary | faq
    content: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True
    )  # {sections: [{heading, body}]}
    tags: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="zh")
    created_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
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
            f"<KnowledgeEntry(id={self.id}, title={self.title!r}, "
            f"category={self.category!r})>"
        )
