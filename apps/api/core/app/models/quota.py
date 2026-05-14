"""Quota ORM model — demographic quota definition for a survey."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Quota(Base):
    """A demographic quota that limits responses within a category.

    When a recipient submits a completed response, the system checks
    all active quotas for the survey. If the recipient's demographics
    match the quota's criteria, current_count is incremented.

    Example: dimension="gender", criteria={"gender": "男"}, target_count=50
    means at most 50 male respondents will be counted.
    """

    __tablename__ = "quotas"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    survey_id: Mapped[str] = mapped_column(
        ForeignKey("surveys.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    dimension: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Demographic dimension, e.g. 'gender', 'age_group', 'education'",
    )
    target_count: Mapped[int] = mapped_column(Integer, nullable=False)
    current_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    criteria: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="Key-value pairs to match, e.g. {'gender': '男'}",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    survey = relationship("Survey", back_populates="quotas")

    def __repr__(self) -> str:
        return (
            f"<Quota(id={self.id}, name={self.name!r}, "
            f"dim={self.dimension}, {self.current_count}/{self.target_count})>"
        )
