"""Add country to user_profiles

Revision ID: 012
Revises: 011
Create Date: 2026-07-05
"""
import sqlalchemy as sa
from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user_profiles") as batch:
        batch.add_column(sa.Column("country", sa.String(100), nullable=True))


def downgrade():
    with op.batch_alter_table("user_profiles") as batch:
        batch.drop_column("country")
