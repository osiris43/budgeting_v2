"""add statement_import status and confirmed_at

Revision ID: 8c0e6d0e1a21
Revises: 5f1b8c8a5c7a
Create Date: 2026-02-21

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8c0e6d0e1a21"
down_revision = "5f1b8c8a5c7a"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("statement_import", schema=None) as batch_op:
        batch_op.add_column(sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"))
        batch_op.add_column(sa.Column("confirmed_at", sa.DateTime(), nullable=True))

    # Clear server default after backfilling existing rows.
    with op.batch_alter_table("statement_import", schema=None) as batch_op:
        batch_op.alter_column("status", server_default=None)


def downgrade():
    with op.batch_alter_table("statement_import", schema=None) as batch_op:
        batch_op.drop_column("confirmed_at")
        batch_op.drop_column("status")
