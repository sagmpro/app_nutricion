"""Add activity_day_configs table, migrate existing activity_days

Revision ID: 014
Revises: 013
Create Date: 2026-07-05
"""
import json
import sqlalchemy as sa
from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "activity_day_configs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("profile_id", sa.Integer, sa.ForeignKey("user_profiles.id"), nullable=False, index=True),
        sa.Column("day_of_week", sa.Integer, nullable=False),
        sa.Column("exercise_type_id", sa.Integer, sa.ForeignKey("exercise_types.id"), nullable=True),
        sa.Column("start_time", sa.String(5), nullable=True),
        sa.Column("end_time", sa.String(5), nullable=True),
    )
    # Migrate existing activity_days + training_time/training_end to per-day configs
    conn = op.get_bind()
    profiles = conn.execute(
        sa.text("SELECT id, activity_days, training_time, training_end FROM user_profiles")
    ).fetchall()
    for p in profiles:
        try:
            days = json.loads(p[1] or "[]")
        except Exception:
            days = []
        start = p[2]
        end = p[3]
        for day in days:
            conn.execute(
                sa.text("""
                    INSERT INTO activity_day_configs (profile_id, day_of_week, exercise_type_id, start_time, end_time)
                    VALUES (:profile_id, :day, NULL, :start, :end)
                """),
                {"profile_id": p[0], "day": day, "start": start, "end": end},
            )


def downgrade():
    op.drop_table("activity_day_configs")
