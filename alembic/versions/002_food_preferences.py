"""Add food preferences to user_profiles

Revision ID: 002
Revises: 001
Create Date: 2026-07-03 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_profiles", sa.Column("dietary_type", sa.String(20), nullable=False, server_default="omnivoro"))
    op.add_column("user_profiles", sa.Column("food_intolerances", sa.String(500), nullable=True))
    op.add_column("user_profiles", sa.Column("disliked_foods", sa.String(500), nullable=True))
    op.add_column("user_profiles", sa.Column("preferred_foods", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("user_profiles", "preferred_foods")
    op.drop_column("user_profiles", "disliked_foods")
    op.drop_column("user_profiles", "food_intolerances")
    op.drop_column("user_profiles", "dietary_type")
