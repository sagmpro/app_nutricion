"""Dedup saved_meals and add unique index on (user_id, meal_type, lower(name))

Revision ID: 019
Revises: 018
Create Date: 2026-08-02
"""
from alembic import op
from sqlalchemy import text

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # Find groups with duplicates (case-insensitive name match)
    dupes = conn.execute(text("""
        SELECT user_id, meal_type, lower(name) AS lname
        FROM saved_meals
        GROUP BY user_id, meal_type, lower(name)
        HAVING COUNT(*) > 1
    """)).fetchall()

    for row in dupes:
        # Keep the row with the highest times_served; on tie, keep the oldest (lowest id)
        best = conn.execute(text("""
            SELECT id FROM saved_meals
            WHERE user_id = :uid
              AND meal_type = :mt
              AND lower(name) = :lname
            ORDER BY times_served DESC, id ASC
            LIMIT 1
        """), {"uid": row.user_id, "mt": row.meal_type, "lname": row.lname}).fetchone()

        if best:
            conn.execute(text("""
                DELETE FROM saved_meals
                WHERE user_id = :uid
                  AND meal_type = :mt
                  AND lower(name) = :lname
                  AND id != :keep_id
            """), {"uid": row.user_id, "mt": row.meal_type, "lname": row.lname, "keep_id": best.id})

    # Add functional unique index — PostgreSQL only (SQLite doesn't support it)
    if conn.dialect.name == "postgresql":
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_saved_meals_user_type_name
            ON saved_meals (user_id, meal_type, lower(name))
        """))


def downgrade():
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        conn.execute(text("DROP INDEX IF EXISTS uq_saved_meals_user_type_name"))
