"""Add lifestyle and cooking fields to profile, consumption to meals

Revision ID: 003
Revises: 002
Create Date: 2026-07-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_profiles", sa.Column("training_time", sa.String(5), nullable=True))
    op.add_column("user_profiles", sa.Column("cooking_facilities", sa.String(500), nullable=True))
    op.add_column("user_profiles", sa.Column("max_meal_repeats", sa.Integer(), nullable=False, server_default="2"))

    op.add_column("meals", sa.Column("consumed", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column("meals", sa.Column("actual_calories", sa.Integer(), nullable=True))
    op.add_column("meals", sa.Column("actual_name", sa.String(200), nullable=True))
    op.add_column("meals", sa.Column("recipe_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("meals", "recipe_text")
    op.drop_column("meals", "actual_name")
    op.drop_column("meals", "actual_calories")
    op.drop_column("meals", "consumed")
    op.drop_column("user_profiles", "max_meal_repeats")
    op.drop_column("user_profiles", "cooking_facilities")
    op.drop_column("user_profiles", "training_time")
