"""add merchant_rule detail_pattern

Revision ID: d4e5f6a7b8c9
Revises: 8c0e6d0e1a21
Create Date: 2026-04-11 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = '8c0e6d0e1a21'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('merchant_rule', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('detail_pattern', sa.String(length=500), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('merchant_rule', schema=None) as batch_op:
        batch_op.drop_column('detail_pattern')
