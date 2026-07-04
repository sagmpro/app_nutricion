"""Add training_end field to user_profiles

Revision ID: 005
Revises: 004
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user_profiles", sa.Column("training_end", sa.String(5), nullable=True))


def downgrade():
    op.drop_column("user_profiles", "training_end")
