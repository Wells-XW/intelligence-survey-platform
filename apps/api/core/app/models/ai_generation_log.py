"""AiGenerationLog ORM model — cost tracking and audit for all AI/LLM calls."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class AiGenerationLog(Base):
    """Immutable log of every AI generation call. Used for cost tracking,
    quality monitoring, and usage analytics.

    Each row corresponds to a single LLM API call (chat completion).
    In the SSE flow, one request may trigger one underlying LLM call.
    """

    __tablename__ = "ai_generation_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: _new_uuid()
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    survey_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("surveys.id", ondelete="SET NULL"), nullable=True, index=True
    )
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="deepseek")
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_cents: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    request_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="generate_survey",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="success"
    )  # "success" | "partial" | "error"
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<AiGenerationLog(id={self.id!r}, model={self.model!r}, "
            f"tokens={self.total_tokens}, cost_cents={self.estimated_cost_cents})>"
        )


def _new_uuid() -> str:
    import uuid
    return str(uuid.uuid4())
