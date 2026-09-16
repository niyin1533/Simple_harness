"""@input Existing memories. @output Nullable governance metadata, preserving all old rows.
@position Additive schema migration. @doc-sync Update INDEX.md on changes.
"""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("memories", sa.Column("meta", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("memories", "meta")
