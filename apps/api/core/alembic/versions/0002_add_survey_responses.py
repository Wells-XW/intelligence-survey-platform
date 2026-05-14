"""v002: Add survey_responses table for collecting respondent data.

Revision ID: 0002_add_survey_responses
Revises: 0001_initial_auth
Create Date: 2026-05-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_add_survey_responses"
down_revision: Union[str, None] = "0001_initial_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "survey_responses",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("survey_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("respondent_id", sa.String(320), nullable=True),
        sa.Column("answers", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("is_complete", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["survey_id"], ["surveys.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_survey_responses_survey_id", "survey_responses", ["survey_id"]
    )
    op.create_index(
        "ix_survey_responses_respondent_id", "survey_responses", ["respondent_id"]
    )
    op.create_index(
        "ix_survey_responses_submitted_at",
        "survey_responses",
        ["submitted_at"],
    )


def downgrade() -> None:
    op.drop_table("survey_responses")
