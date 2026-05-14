"""SurveyPermission ORM model — RBAC at survey level."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class SurveyPermission(Base):
    """Grants a user a specific role on a survey (owner / editor / viewer)."""

    __tablename__ = "survey_permissions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    survey_id: Mapped[str] = mapped_column(
        ForeignKey("surveys.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # owner | editor | viewer
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user = relationship("User")
    survey = relationship("Survey", back_populates="permissions")

    __table_args__ = (
        UniqueConstraint("user_id", "survey_id", name="uq_user_survey_permission"),
    )

    def __repr__(self) -> str:
        return (
            f"<SurveyPermission(user_id={self.user_id}, "
            f"survey_id={self.survey_id}, role={self.role!r})>"
        )
