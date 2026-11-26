"""Phase 2 review workflow: finding dismissal fields, review cancellation fields, GitHub comment deletion fields

Revision ID: 0004
Revises: 0003

Idempotent: a database created by the 0001 baseline from CURRENT model metadata already has these columns.
Foreign keys are added only on PostgreSQL (SQLite cannot ALTER TABLE ADD CONSTRAINT); the models declare them everywhere.
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

COLUMNS = [
    ("code_reviews", sa.Column("cancelled_by_id", sa.Integer(), nullable=True), True),
    ("code_reviews", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True), False),
    ("review_findings", sa.Column("dismissed_by_id", sa.Integer(), nullable=True), True),
    ("review_findings", sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True), False),
    ("review_findings", sa.Column("dismiss_reason", sa.String(40), nullable=True), False),
    ("review_findings", sa.Column("dismiss_note", sa.String(300), nullable=True), False),
    ("review_comments", sa.Column("github_deleted_at", sa.DateTime(timezone=True), nullable=True), False),
    ("review_comments", sa.Column("github_deleted_by_id", sa.Integer(), nullable=True), True),
]


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table, col, is_user_fk in COLUMNS:
        if not insp.has_table(table) or col.name in {c["name"] for c in insp.get_columns(table)}:
            continue
        op.add_column(table, col)
        if is_user_fk and bind.dialect.name == "postgresql":
            op.create_foreign_key(f"fk_{table}_{col.name}", table, "users", [col.name], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    for table, col, _ in reversed(COLUMNS):
        if insp.has_table(table) and col.name in {c["name"] for c in insp.get_columns(table)}:
            op.drop_column(table, col.name)
