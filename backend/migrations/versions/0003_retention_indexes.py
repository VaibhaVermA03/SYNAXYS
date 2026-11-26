"""indexes that keep the retention cleanup cheap (sessions, webhook deliveries, jobs, audit log)

Revision ID: 0003
Revises: 0002

Idempotent: a database created by the 0001 baseline from CURRENT model metadata already has these indexes.
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

INDEXES = [
    ("ix_user_sessions_expires_at", "user_sessions", ["expires_at"]),
    ("ix_webhook_deliveries_received_at", "webhook_deliveries", ["received_at"]),
    ("ix_jobs_status_finished_at", "background_jobs", ["status", "finished_at"]),
    ("ix_audit_logs_created_at", "audit_logs", ["created_at"]),
]


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    for name, table, cols in INDEXES:
        if insp.has_table(table) and name not in {i["name"] for i in insp.get_indexes(table)}:
            op.create_index(name, table, cols)


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    for name, table, _ in INDEXES:
        if insp.has_table(table) and name in {i["name"] for i in insp.get_indexes(table)}:
            op.drop_index(name, table_name=table)
