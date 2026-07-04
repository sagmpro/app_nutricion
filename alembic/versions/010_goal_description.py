"""Add goal_description to user_profiles

Revision ID: 010
Revises: 009
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def _col_exists(conn, table, col):
    return col in [c["name"] for c in inspect(conn).get_columns(table)]


def upgrade():
    conn = op.get_bind()
    if not _col_exists(conn, "user_profiles", "goal_description"):
        op.add_column("user_profiles", sa.Column("goal_description", sa.Text(), nullable=True))


def downgrade():
    conn = op.get_bind()
    if _col_exists(conn, "user_profiles", "goal_description"):
        op.drop_column("user_profiles", "goal_description")
