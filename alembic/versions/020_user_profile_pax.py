"""Add pax column to user_profiles

Revision ID: 020
Revises: 019
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    # SQLite and PostgreSQL both support ALTER TABLE ADD COLUMN with a default
    if conn.dialect.name == "postgresql":
        conn.execute(sa.text(
            "ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS pax FLOAT NOT NULL DEFAULT 1.0"
        ))
    else:
        # SQLite
        try:
            conn.execute(sa.text(
                "ALTER TABLE user_profiles ADD COLUMN pax FLOAT NOT NULL DEFAULT 1.0"
            ))
        except Exception:
            pass  # column already exists


def downgrade():
    # SQLite doesn't support DROP COLUMN; PostgreSQL does
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        conn.execute(sa.text("ALTER TABLE user_profiles DROP COLUMN IF EXISTS pax"))
