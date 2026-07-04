"""Add users, invitations tables; add user_id to profiles and stock

Revision ID: 006
Revises: 005
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return name in insp.get_table_names()


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    cols = [c["name"] for c in insp.get_columns(table)]
    return column in cols


def _index_exists(index_name: str, table_name: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return any(ix["name"] == index_name for ix in insp.get_indexes(table_name))


def upgrade():
    if not _table_exists("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("email", sa.String(255), nullable=False, unique=True),
            sa.Column("hashed_password", sa.String(255), nullable=True),
            sa.Column("role", sa.String(20), nullable=False, server_default="user"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
    if not _index_exists("ix_users_email", "users"):
        op.create_index("ix_users_email", "users", ["email"])

    if not _table_exists("invitations"):
        op.create_table(
            "invitations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("token", sa.String(64), nullable=False, unique=True),
            sa.Column("invited_by", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("used", sa.Boolean(), nullable=False, server_default="0"),
        )
    if not _index_exists("ix_invitations_token", "invitations"):
        op.create_index("ix_invitations_token", "invitations", ["token"])

    # Use plain Integer (no FK constraint) for SQLite compatibility when adding columns.
    # PostgreSQL in production enforces the FK at the model level.
    if not _column_exists("user_profiles", "user_id"):
        op.add_column("user_profiles", sa.Column("user_id", sa.Integer(), nullable=True))
    if not _index_exists("ix_user_profiles_user_id", "user_profiles"):
        op.create_index("ix_user_profiles_user_id", "user_profiles", ["user_id"])

    if not _column_exists("food_stock", "user_id"):
        op.add_column("food_stock", sa.Column("user_id", sa.Integer(), nullable=True))
    if not _index_exists("ix_food_stock_user_id", "food_stock"):
        op.create_index("ix_food_stock_user_id", "food_stock", ["user_id"])


def downgrade():
    try:
        op.drop_index("ix_food_stock_user_id", "food_stock")
    except Exception:
        pass
    try:
        op.drop_column("food_stock", "user_id")
    except Exception:
        pass
    try:
        op.drop_index("ix_user_profiles_user_id", "user_profiles")
    except Exception:
        pass
    try:
        op.drop_column("user_profiles", "user_id")
    except Exception:
        pass
    try:
        op.drop_table("invitations")
    except Exception:
        pass
    try:
        op.drop_table("users")
    except Exception:
        pass
