"""Deduplicate saved_meals by (user_id, name, meal_type)

Revision ID: 011
Revises: 010
Create Date: 2026-07-05
"""
from alembic import op
from sqlalchemy import text

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # Find groups with more than one row
    dupes = bind.execute(text(
        "SELECT user_id, name, meal_type FROM saved_meals "
        "GROUP BY user_id, name, meal_type HAVING COUNT(*) > 1"
    )).fetchall()

    for row in dupes:
        user_id, name, meal_type = row[0], row[1], row[2]

        # Fetch all rows for this group, best first
        rows = bind.execute(text(
            "SELECT id, times_served FROM saved_meals "
            "WHERE user_id = :u AND name = :n AND meal_type = :mt "
            "ORDER BY "
            "  CASE WHEN rating IS NOT NULL THEN 0 ELSE 1 END, "
            "  times_served DESC, id DESC"
        ), {"u": user_id, "n": name, "mt": meal_type}).fetchall()

        keep_id = rows[0][0]
        total_served = sum(r[1] for r in rows)
        delete_ids = [r[0] for r in rows[1:]]

        bind.execute(text(
            "UPDATE saved_meals SET times_served = :ts WHERE id = :id"
        ), {"ts": total_served, "id": keep_id})

        for del_id in delete_ids:
            bind.execute(text("DELETE FROM saved_meals WHERE id = :id"), {"id": del_id})


def downgrade():
    pass  # irreversible data cleanup
