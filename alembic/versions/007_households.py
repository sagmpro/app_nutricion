"""Add households, household_members; add household_id to stock/shopping/plans; add shared_plan_mode to profiles

Revision ID: 007
Revises: 006
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def _table_exists(conn, name):
    return inspect(conn).has_table(name)


def _column_exists(conn, table, column):
    cols = [c["name"] for c in inspect(conn).get_columns(table)]
    return column in cols


def upgrade():
    conn = op.get_bind()

    if not _table_exists(conn, "households"):
        op.create_table(
            "households",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        )

    if not _table_exists(conn, "household_members"):
        op.create_table(
            "household_members",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("household_id", sa.Integer, sa.ForeignKey("households.id"), nullable=False),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False, unique=True),
            sa.Column("role", sa.String(20), nullable=False, server_default="member"),
            sa.Column("joined_at", sa.DateTime, server_default=sa.func.now()),
        )
        op.create_index("ix_household_members_household_id", "household_members", ["household_id"])
        op.create_index("ix_household_members_user_id", "household_members", ["user_id"])

    if not _column_exists(conn, "food_stock", "household_id"):
        op.add_column("food_stock", sa.Column("household_id", sa.Integer, nullable=True))
        op.create_index("ix_food_stock_household_id", "food_stock", ["household_id"])

    if not _column_exists(conn, "shopping_lists", "household_id"):
        op.add_column("shopping_lists", sa.Column("household_id", sa.Integer, nullable=True))
        op.create_index("ix_shopping_lists_household_id", "shopping_lists", ["household_id"])

    if not _column_exists(conn, "meal_plans", "is_shared"):
        op.add_column("meal_plans", sa.Column("is_shared", sa.Boolean, nullable=False, server_default="false"))

    if not _column_exists(conn, "meal_plans", "household_id"):
        op.add_column("meal_plans", sa.Column("household_id", sa.Integer, nullable=True))
        op.create_index("ix_meal_plans_household_id", "meal_plans", ["household_id"])

    if not _column_exists(conn, "user_profiles", "shared_plan_mode"):
        op.add_column("user_profiles", sa.Column("shared_plan_mode", sa.String(10), nullable=False, server_default="own"))


def downgrade():
    conn = op.get_bind()

    if _column_exists(conn, "user_profiles", "shared_plan_mode"):
        op.drop_column("user_profiles", "shared_plan_mode")

    if _column_exists(conn, "meal_plans", "household_id"):
        op.drop_index("ix_meal_plans_household_id", "meal_plans")
        op.drop_column("meal_plans", "household_id")

    if _column_exists(conn, "meal_plans", "is_shared"):
        op.drop_column("meal_plans", "is_shared")

    if _column_exists(conn, "shopping_lists", "household_id"):
        op.drop_index("ix_shopping_lists_household_id", "shopping_lists")
        op.drop_column("shopping_lists", "household_id")

    if _column_exists(conn, "food_stock", "household_id"):
        op.drop_index("ix_food_stock_household_id", "food_stock")
        op.drop_column("food_stock", "household_id")

    if _table_exists(conn, "household_members"):
        op.drop_table("household_members")

    if _table_exists(conn, "households"):
        op.drop_table("households")
