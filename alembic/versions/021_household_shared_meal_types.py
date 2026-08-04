"""Add shared_meal_types column to households

Revision ID: 021
Revises: 020
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None

_DEFAULT = '["almuerzo"]'


def upgrade():
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        conn.execute(sa.text(
            f"ALTER TABLE households ADD COLUMN IF NOT EXISTS shared_meal_types TEXT NOT NULL DEFAULT '{_DEFAULT}'"
        ))
    else:
        try:
            conn.execute(sa.text(
                f"ALTER TABLE households ADD COLUMN shared_meal_types TEXT NOT NULL DEFAULT '{_DEFAULT}'"
            ))
        except Exception:
            pass  # column already exists


def downgrade():
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        conn.execute(sa.text("ALTER TABLE households DROP COLUMN IF EXISTS shared_meal_types"))
