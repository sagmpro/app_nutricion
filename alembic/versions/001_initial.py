"""Initial schema

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, server_default="Usuario"),
        sa.Column("age", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("gender", sa.String(10), nullable=False, server_default="male"),
        sa.Column("weight_kg", sa.Float(), nullable=False, server_default="70.0"),
        sa.Column("height_cm", sa.Float(), nullable=False, server_default="170.0"),
        sa.Column("goal_type", sa.String(20), nullable=False, server_default="caloric_deficit"),
        sa.Column("target_calories", sa.Integer(), nullable=True),
        sa.Column("current_fat_pct", sa.Float(), nullable=True),
        sa.Column("target_fat_pct", sa.Float(), nullable=True),
        sa.Column("target_days", sa.Integer(), nullable=True),
        sa.Column("activity_days", sa.String(50), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "meal_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("user_profiles.id"), nullable=False, index=True),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "meals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("meal_plan_id", sa.Integer(), sa.ForeignKey("meal_plans.id"), nullable=False, index=True),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("meal_type", sa.String(20), nullable=False),
        sa.Column("meal_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("calories", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("protein_g", sa.Float(), nullable=False, server_default="0"),
        sa.Column("carbs_g", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fat_g", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ingredients_json", sa.Text(), nullable=False, server_default="[]"),
    )

    op.create_table(
        "shopping_lists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("meal_plan_id", sa.Integer(), sa.ForeignKey("meal_plans.id"), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "shopping_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shopping_list_id", sa.Integer(), sa.ForeignKey("shopping_lists.id"), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unit", sa.String(50), nullable=False, server_default="unidades"),
        sa.Column("category", sa.String(100), nullable=False, server_default="Otros"),
        sa.Column("checked", sa.Boolean(), nullable=False, server_default="0"),
    )

    op.create_table(
        "food_stock",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unit", sa.String(50), nullable=False, server_default="unidades"),
        sa.Column("category", sa.String(100), nullable=False, server_default="Otros"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade() -> None:
    op.drop_table("food_stock")
    op.drop_table("shopping_items")
    op.drop_table("shopping_lists")
    op.drop_table("meals")
    op.drop_table("meal_plans")
    op.drop_table("user_profiles")
