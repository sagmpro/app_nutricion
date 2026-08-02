"""Add model column to token_usage

Revision ID: 017
Revises: 016
Create Date: 2026-08-02
"""
import sqlalchemy as sa
from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("token_usage", sa.Column("model", sa.String(80), nullable=True))


def downgrade():
    op.drop_column("token_usage", "model")
