"""add card_no and bank_category_raw

Revision ID: 2b7c5a4b6e2d
Revises: a9c948fde07a
Create Date: 2026-02-19

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2b7c5a4b6e2d"
down_revision = "a9c948fde07a"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("transaction", schema=None) as batch_op:
        batch_op.add_column(sa.Column("card_no", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("bank_category_raw", sa.String(length=200), nullable=True))


def downgrade():
    with op.batch_alter_table("transaction", schema=None) as batch_op:
        batch_op.drop_column("bank_category_raw")
        batch_op.drop_column("card_no")
