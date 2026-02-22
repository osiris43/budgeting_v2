"""add account invert_csv_amounts

Revision ID: c3d1f2a9b0aa
Revises: 8c0e6d0e1a21
Create Date: 2026-02-22

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c3d1f2a9b0aa"
down_revision = "8c0e6d0e1a21"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("account", schema=None) as batch_op:
        batch_op.add_column(sa.Column("invert_csv_amounts", sa.Boolean(), nullable=False, server_default=sa.false()))

    # Clear server default after backfilling existing rows.
    with op.batch_alter_table("account", schema=None) as batch_op:
        batch_op.alter_column("invert_csv_amounts", server_default=None)


def downgrade():
    with op.batch_alter_table("account", schema=None) as batch_op:
        batch_op.drop_column("invert_csv_amounts")
