"""ai_action_log table for AI usage limits

Revision ID: 018
Revises: 017
Create Date: 2026-08-02
"""
from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_action_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ai_action_log_user_id", "ai_action_log", ["user_id"])
    op.create_index("ix_ai_action_log_action_created", "ai_action_log", ["user_id", "action", "created_at"])


def downgrade():
    op.drop_table("ai_action_log")
