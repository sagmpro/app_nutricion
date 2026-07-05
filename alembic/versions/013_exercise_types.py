"""Add exercise_types table with defaults

Revision ID: 013
Revises: 012
Create Date: 2026-07-05
"""
import sqlalchemy as sa
from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None

DEFAULT_TYPES = [
    ("Gym / Pesas", "🏋️"),
    ("Running", "🏃"),
    ("Ciclismo", "🚴"),
    ("Natación", "🏊"),
    ("HIIT / Funcional", "🥊"),
    ("Yoga / Pilates", "🧘"),
    ("Fútbol / Deporte", "⚽"),
    ("Caminata", "🚶"),
]


def upgrade():
    op.create_table(
        "exercise_types",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("icon", sa.String(10), nullable=False, server_default="🏃"),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
    )
    conn = op.get_bind()
    for name, icon in DEFAULT_TYPES:
        conn.execute(
            sa.text("INSERT INTO exercise_types (name, icon, is_default) VALUES (:name, :icon, TRUE)"),
            {"name": name, "icon": icon},
        )


def downgrade():
    op.drop_table("exercise_types")
