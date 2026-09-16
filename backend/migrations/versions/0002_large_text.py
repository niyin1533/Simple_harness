"""@input Initial text columns. @output Long text capacity matching upload/message contracts.
@position Schema history. @doc-sync Update INDEX.md on changes.
"""

from alembic import op
from sqlalchemy.dialects.mysql import LONGTEXT

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None
COLUMNS = {
    "resources": ["description", "content", "secret"],
    "messages": ["content"],
    "runs": ["task", "result", "error"],
    "checkpoints": ["summary"],
    "memories": ["content"],
    "preferences": ["secret"],
    "artifacts": ["path"],
    "deployments": ["error"],
    "schedules": ["task"],
}


def upgrade():
    for table, columns in COLUMNS.items():
        for column in columns:
            op.alter_column(
                table, column, type_=LONGTEXT(), existing_nullable=column == "secret"
            )


def downgrade():
    raise RuntimeError(
        "Narrowing text may destroy data; restore a verified backup instead."
    )
