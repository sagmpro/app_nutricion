"""Add display_name to household_members

Revision ID: 022
Revises: 021
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("household_members") as batch_op:
        batch_op.add_column(
            sa.Column("display_name", sa.String(80), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("household_members") as batch_op:
        batch_op.drop_column("display_name")
