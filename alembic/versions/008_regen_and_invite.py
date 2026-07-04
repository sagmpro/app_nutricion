"""Add regen_count to meals; add invite_token to households

Revision ID: 008
Revises: 007
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
import uuid

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def _table_exists(conn, name):
    return inspect(conn).has_table(name)


def _column_exists(conn, table, column):
    cols = [c["name"] for c in inspect(conn).get_columns(table)]
    return column in cols


def upgrade():
    conn = op.get_bind()

    if not _column_exists(conn, "meals", "regen_count"):
        op.add_column("meals", sa.Column("regen_count", sa.Integer, nullable=False, server_default="0"))

    if _table_exists(conn, "households") and not _column_exists(conn, "households", "invite_token"):
        op.add_column("households", sa.Column("invite_token", sa.String(64), nullable=True))
        op.create_index("ix_households_invite_token", "households", ["invite_token"])
        # Backfill existing households with a unique token
        conn.execute(sa.text("UPDATE households SET invite_token = lower(hex(randomblob(16))) WHERE invite_token IS NULL"))


def downgrade():
    conn = op.get_bind()

    if _column_exists(conn, "meals", "regen_count"):
        op.drop_column("meals", "regen_count")

    if _table_exists(conn, "households") and _column_exists(conn, "households", "invite_token"):
        op.drop_index("ix_households_invite_token", "households")
        op.drop_column("households", "invite_token")
