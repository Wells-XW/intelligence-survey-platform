"""Add ai_generation_logs table for AI call tracking and cost monitoring.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_generation_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("survey_id", sa.String(36), sa.ForeignKey("surveys.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False, server_default="deepseek"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_cents", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("request_type", sa.String(50), nullable=False, server_default="generate_survey"),
        sa.Column("status", sa.String(20), nullable=False, server_default="success"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True),
    )


def downgrade() -> None:
    op.drop_table("ai_generation_logs")
