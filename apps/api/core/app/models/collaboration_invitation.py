"""CollaborationInvitation ORM model — pending invitations to collaborate."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class CollaborationInvitation(Base):
    """Pending invitation to collaborate on a survey.

    Stores an email + role + unique token.  When the recipient clicks
    the acceptance link, a ``SurveyPermission`` row is created and the
    invitation status flips to 'accepted'.
    """

    __tablename__ = "collaboration_invitations"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    survey_id: Mapped[str] = mapped_column(
        ForeignKey("surveys.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    inviter_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(
        String(320), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="viewer"
    )  # 'editor' | 'viewer' (never 'owner')
    token: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True,
        default=lambda: secrets.token_urlsafe(32),
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending | accepted | declined | expired
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc) + timedelta(days=7),
    )

    # Relationships
    survey = relationship("Survey")
    inviter = relationship("User", foreign_keys=[inviter_id])

    def __repr__(self) -> str:
        return (
            f"<CollaborationInvitation(id={self.id}, email={self.email!r}, "
            f"role={self.role!r}, status={self.status!r})>"
        )
