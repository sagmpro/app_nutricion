"""meal schedule: enabled meals and meal times per profile

Revision ID: 004
Revises: 003
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user_profiles", sa.Column("enabled_meals", sa.Text(), nullable=True))
    op.add_column("user_profiles", sa.Column("meal_times", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("user_profiles", "meal_times")
    op.drop_column("user_profiles", "enabled_meals")
