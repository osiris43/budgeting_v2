"""add statement source config

Revision ID: b6a1e2c3d4f5
Revises: d4e5f6a7b8c9
Create Date: 2026-10-02 09:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b6a1e2c3d4f5"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "statement_source_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("username_ref", sa.String(length=500), nullable=False),
        sa.Column("password_ref", sa.String(length=500), nullable=False),
        sa.Column("statement_close_day", sa.Integer(), nullable=False),
        sa.Column("download_dir", sa.String(length=500), nullable=False),
        sa.Column("browser_state_path", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id"),
    )


def downgrade():
    op.drop_table("statement_source_config")
