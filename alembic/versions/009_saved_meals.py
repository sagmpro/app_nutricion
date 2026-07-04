"""Add saved_meals table for recipe repository

Revision ID: 009
Revises: 008
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def _table_exists(conn, name):
    return inspect(conn).has_table(name)


def upgrade():
    conn = op.get_bind()
    if not _table_exists(conn, "saved_meals"):
        op.create_table(
            "saved_meals",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("meal_type", sa.String(20), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("calories", sa.Integer, default=0),
            sa.Column("protein_g", sa.Float, default=0.0),
            sa.Column("carbs_g", sa.Float, default=0.0),
            sa.Column("fat_g", sa.Float, default=0.0),
            sa.Column("ingredients_json", sa.Text, default="[]"),
            sa.Column("recipe_text", sa.Text, nullable=True),
            sa.Column("rating", sa.Integer, nullable=True),
            sa.Column("is_healthy", sa.Boolean, nullable=True),
            sa.Column("is_excluded", sa.Boolean, default=False),
            sa.Column("times_served", sa.Integer, default=1),
            sa.Column("last_served_at", sa.DateTime, nullable=True),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        )
        op.create_index("ix_saved_meals_user_id", "saved_meals", ["user_id"])


def downgrade():
    conn = op.get_bind()
    if _table_exists(conn, "saved_meals"):
        op.drop_index("ix_saved_meals_user_id", "saved_meals")
        op.drop_table("saved_meals")
