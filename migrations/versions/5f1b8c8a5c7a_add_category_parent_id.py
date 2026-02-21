"""add category parent_id

Revision ID: 5f1b8c8a5c7a
Revises: 2b7c5a4b6e2d
Create Date: 2026-02-21

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "5f1b8c8a5c7a"
down_revision = "2b7c5a4b6e2d"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("category", schema=None) as batch_op:
        batch_op.add_column(sa.Column("parent_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_category_parent", "category", ["parent_id"], ["id"])


def downgrade():
    with op.batch_alter_table("category", schema=None) as batch_op:
        batch_op.drop_constraint("fk_category_parent", type_="foreignkey")
        batch_op.drop_column("parent_id")
