"""Add token_usage table for tracking Claude API consumption per user

Revision ID: 015
Revises: 014
Create Date: 2026-08-02
"""
import sqlalchemy as sa
from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "token_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("function_name", sa.String(80), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, default=0),
        sa.Column("output_tokens", sa.Integer(), nullable=False, default=0),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_token_usage_user_id", "token_usage", ["user_id"])
    op.create_index("ix_token_usage_created_at", "token_usage", ["created_at"])


def downgrade():
    op.drop_table("token_usage")
