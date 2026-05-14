"""ConsentRecord ORM model — PIPL informed consent tracking."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class ConsentRecord(Base):
    """Records user consent for privacy policy, data processing, etc.

    PIPL Articles 13-17 require explicit, informed consent before
    collecting personal information.
    """

    __tablename__ = "consent_records"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    consent_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # privacy_policy | data_processing | data_export
    consent_version: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # e.g. "v1.0", "v2.0"
    ip_address: Mapped[str] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str] = mapped_column(Text, nullable=True)
    agreed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint(
            "user_id", "consent_type", name="uq_user_consent_type"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ConsentRecord(user_id={self.user_id}, "
            f"type={self.consent_type!r}, version={self.consent_version!r})>"
        )
