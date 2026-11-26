"""Phase 3: branch-aware, batch-tracked partial indexing

Revision ID: 0005
Revises: 0004

* new tables: indexed_branch_files (replaces indexed_files; unique key now includes the branch), branch_index_states, indexing_batches
* new columns: indexing_jobs.plan_summary/continuations, review_configurations.index_include_globs/index_exclude_globs/index_max_files
* data: every row of the old indexed_files table is copied with branch = the repository's default branch and vector_schema = 1 (legacy vector ids);
  the first branch-aware index run re-embeds those files under the new ids and deletes the legacy vectors. Repositories that were 'indexed' get a
  branch_index_states row so they stay searchable meanwhile. Then the old table is dropped.
Idempotent: a database created by the 0001 baseline from CURRENT model metadata already has the new tables/columns.
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

DT = sa.DateTime(timezone=True)


def _cols(insp, table):
    return {c["name"] for c in insp.get_columns(table)} if insp.has_table(table) else set()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("indexed_branch_files"):
        op.create_table("indexed_branch_files",
                        sa.Column("id", sa.Integer(), primary_key=True),
                        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
                        sa.Column("branch", sa.String(200), nullable=False, server_default=""),
                        sa.Column("vector_schema", sa.Integer(), nullable=False, server_default="2"),
                        sa.Column("path", sa.String(1000), nullable=False),
                        sa.Column("blob_sha", sa.String(64), nullable=False),
                        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
                        sa.Column("commit_sha", sa.String(64)),
                        sa.Column("indexed_at", DT, nullable=False, server_default=sa.func.now()),
                        sa.UniqueConstraint("repository_id", "branch", "path"))
        op.create_index("ix_indexed_branch_files_repository_id", "indexed_branch_files", ["repository_id"])
        op.create_index("ix_ibf_repo_branch", "indexed_branch_files", ["repository_id", "branch"])
    if not insp.has_table("branch_index_states"):
        op.create_table("branch_index_states",
                        sa.Column("id", sa.Integer(), primary_key=True),
                        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
                        sa.Column("branch", sa.String(200), nullable=False),
                        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
                        sa.Column("last_indexed_commit", sa.String(64)),
                        sa.Column("last_indexed_at", DT),
                        sa.Column("error", sa.String(500)),
                        sa.Column("files_indexed", sa.Integer(), nullable=False, server_default="0"),
                        sa.Column("files_eligible", sa.Integer(), nullable=False, server_default="0"),
                        sa.Column("files_deferred", sa.Integer(), nullable=False, server_default="0"),
                        sa.Column("failed_batches", sa.Integer(), nullable=False, server_default="0"),
                        sa.Column("tree_incomplete", sa.Boolean(), nullable=False, server_default=sa.false()),
                        sa.Column("updated_at", DT, nullable=False, server_default=sa.func.now()),
                        sa.UniqueConstraint("repository_id", "branch"))
        op.create_index("ix_branch_index_states_repository_id", "branch_index_states", ["repository_id"])
    if not insp.has_table("indexing_batches"):
        op.create_table("indexing_batches",
                        sa.Column("id", sa.Integer(), primary_key=True),
                        sa.Column("job_id", sa.Integer(), sa.ForeignKey("indexing_jobs.id", ondelete="CASCADE"), nullable=False),
                        sa.Column("seq", sa.Integer(), nullable=False),
                        sa.Column("kind", sa.String(10), nullable=False),
                        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
                        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
                        sa.Column("items", sa.JSON(), nullable=False),
                        sa.Column("files_done", sa.Integer(), nullable=False, server_default="0"),
                        sa.Column("chunks", sa.Integer(), nullable=False, server_default="0"),
                        sa.Column("error", sa.String(500)),
                        sa.Column("updated_at", DT, nullable=False, server_default=sa.func.now()),
                        sa.UniqueConstraint("job_id", "seq"))
        op.create_index("ix_indexing_batches_job_id", "indexing_batches", ["job_id"])
    for table, col in [("indexing_jobs", sa.Column("plan_summary", sa.JSON())), ("indexing_jobs", sa.Column("continuations", sa.Integer(), nullable=False, server_default="0")),
                       ("review_configurations", sa.Column("index_include_globs", sa.JSON())), ("review_configurations", sa.Column("index_exclude_globs", sa.JSON())),
                       ("review_configurations", sa.Column("index_max_files", sa.Integer()))]:
        if insp.has_table(table) and col.name not in _cols(insp, table):
            op.add_column(table, col)
    insp = sa.inspect(bind)
    if insp.has_table("indexed_files"):  # legacy -> new, only into an empty new table (re-running never duplicates)
        if not bind.execute(sa.text("SELECT 1 FROM indexed_branch_files LIMIT 1")).first():
            bind.execute(sa.text(
                "INSERT INTO indexed_branch_files (repository_id, branch, vector_schema, path, blob_sha, chunk_count, commit_sha, indexed_at) "
                "SELECT f.repository_id, r.default_branch, 1, f.path, f.blob_sha, f.chunk_count, f.commit_sha, f.indexed_at "
                "FROM indexed_files f JOIN repositories r ON r.id = f.repository_id"))
        if not bind.execute(sa.text("SELECT 1 FROM branch_index_states LIMIT 1")).first():
            bind.execute(sa.text(
                "INSERT INTO branch_index_states (repository_id, branch, status, last_indexed_commit, last_indexed_at, files_indexed, files_eligible, files_deferred, failed_batches, tree_incomplete, updated_at) "
                "SELECT r.id, r.default_branch, 'indexed', r.last_indexed_commit, r.last_indexed_at, "
                "(SELECT COUNT(*) FROM indexed_files f WHERE f.repository_id = r.id), 0, 0, 0, :f, CURRENT_TIMESTAMP "
                "FROM repositories r WHERE r.index_status = 'indexed'"), {"f": False})
        op.drop_table("indexed_files")


def downgrade() -> None:
    """Not supported: the old single-branch table cannot represent several branches. Restore from a backup instead."""
    raise NotImplementedError("0005 cannot be downgraded; restore a database backup")
