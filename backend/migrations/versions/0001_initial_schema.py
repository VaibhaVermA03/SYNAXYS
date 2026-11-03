"""initial schema

Revision ID: 0001
Revises:

NOTE: The baseline creates tables from the model metadata as of this release
(hand-pinning 17 tables here would duplicate the models). Every LATER change
MUST be an explicit, reviewed migration (alembic revision --autogenerate).
Never run destructive init in production: downgrade() only drops what this
baseline created and is guarded off in production by operators' process.
"""
from alembic import op

import app.models  # noqa: F401
from app.db.base import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
