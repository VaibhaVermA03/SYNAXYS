"""indexed_files (incremental indexing state)

Revision ID: 0002
Revises: 0001

Idempotent: a database created by the 0001 baseline from CURRENT model metadata already has this table.
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("indexed_files"):
        return
    op.create_table(
        "indexed_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("path", sa.String(1000), nullable=False),
        sa.Column("blob_sha", sa.String(64), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("commit_sha", sa.String(64)),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("repository_id", "path"),
    )
    op.create_index("ix_indexed_files_repository_id", "indexed_files", ["repository_id"])


def downgrade() -> None:
    op.drop_table("indexed_files")
