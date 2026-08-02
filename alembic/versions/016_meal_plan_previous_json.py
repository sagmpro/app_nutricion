"""Add previous_raw_json to meal_plans for regenerate undo

Revision ID: 016
Revises: 015
Create Date: 2026-08-02
"""
import sqlalchemy as sa
from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("meal_plans", sa.Column("previous_raw_json", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("meal_plans", "previous_raw_json")
