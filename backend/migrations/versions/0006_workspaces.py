"""Phase 4: workspaces, members, invitations, notifications, data exports

Revision ID: 0006
Revises: 0005

* new tables: workspaces, workspace_members, workspace_invitations, notifications, data_exports
* new columns: repositories.workspace_id, audit_logs.workspace_id
* data: existing access is converted WITHOUT widening it. Repositories whose (user, role) sets in repository_access are identical share one workspace
  (single user: "<login>'s workspace", several users: "Shared workspace N"); users that have no repository get a personal workspace.
  repository_access itself stays: from now on it is DERIVED from workspace membership for repositories that belong to a workspace.
Idempotent: a database created by the 0001 baseline from CURRENT model metadata already has the tables/columns, and the data step only runs while no workspace exists.
"""
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

from app.services.workspace_logic import group_legacy_access

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None
DT = sa.DateTime(timezone=True)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("workspaces"):
        op.create_table("workspaces", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(100), nullable=False),
                        sa.Column("invite_policy", sa.String(10), nullable=False, server_default="admin"),
                        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
                        sa.Column("created_at", DT, nullable=False, server_default=sa.func.now()), sa.Column("updated_at", DT, nullable=False, server_default=sa.func.now()))
    if not insp.has_table("workspace_members"):
        op.create_table("workspace_members", sa.Column("id", sa.Integer(), primary_key=True),
                        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
                        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
                        sa.Column("role", sa.String(10), nullable=False, server_default="member"),
                        sa.Column("invited_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
                        sa.Column("created_at", DT, nullable=False, server_default=sa.func.now()), sa.UniqueConstraint("workspace_id", "user_id"))
        op.create_index("ix_workspace_members_workspace_id", "workspace_members", ["workspace_id"])
        op.create_index("ix_workspace_members_user_id", "workspace_members", ["user_id"])
    if not insp.has_table("workspace_invitations"):
        op.create_table("workspace_invitations", sa.Column("id", sa.Integer(), primary_key=True),
                        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
                        sa.Column("invited_login", sa.String(100), nullable=False), sa.Column("role", sa.String(10), nullable=False, server_default="member"),
                        sa.Column("token_hash", sa.String(64), nullable=False, unique=True), sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
                        sa.Column("invited_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
                        sa.Column("accepted_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
                        sa.Column("expires_at", DT, nullable=False), sa.Column("created_at", DT, nullable=False, server_default=sa.func.now()), sa.Column("responded_at", DT))
        op.create_index("ix_workspace_invitations_workspace_id", "workspace_invitations", ["workspace_id"])
        op.create_index("ix_workspace_invitations_invited_login", "workspace_invitations", ["invited_login"])
    if not insp.has_table("notifications"):
        op.create_table("notifications", sa.Column("id", sa.Integer(), primary_key=True),
                        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
                        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE")),
                        sa.Column("kind", sa.String(40), nullable=False), sa.Column("title", sa.String(200), nullable=False), sa.Column("body", sa.String(500)),
                        sa.Column("link", sa.String(300)), sa.Column("dedup_key", sa.String(200), nullable=False), sa.Column("read_at", DT),
                        sa.Column("created_at", DT, nullable=False, server_default=sa.func.now()), sa.UniqueConstraint("user_id", "dedup_key"))
        op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
        op.create_index("ix_notifications_workspace_id", "notifications", ["workspace_id"])
        op.create_index("ix_notifications_user_read", "notifications", ["user_id", "read_at"])
    if not insp.has_table("data_exports"):
        op.create_table("data_exports", sa.Column("id", sa.Integer(), primary_key=True),
                        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
                        sa.Column("status", sa.String(10), nullable=False, server_default="pending"), sa.Column("payload", sa.LargeBinary()),
                        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"), sa.Column("error", sa.String(300)),
                        sa.Column("created_at", DT, nullable=False, server_default=sa.func.now()), sa.Column("expires_at", DT, nullable=False), sa.Column("downloaded_at", DT))
        op.create_index("ix_data_exports_user_id", "data_exports", ["user_id"])
    insp = sa.inspect(bind)
    for table in ("repositories", "audit_logs"):
        if insp.has_table(table) and "workspace_id" not in {c["name"] for c in insp.get_columns(table)}:
            op.add_column(table, sa.Column("workspace_id", sa.Integer(), nullable=True))
            op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])
            if bind.dialect.name == "postgresql":
                op.create_foreign_key(f"fk_{table}_workspace_id", table, "workspaces", ["workspace_id"], ["id"], ondelete="SET NULL")
    _convert_existing_access(bind)


def _convert_existing_access(bind) -> None:
    if bind.execute(sa.text("SELECT 1 FROM workspaces LIMIT 1")).first():
        return  # already converted (or created through the app)
    now = datetime.now(timezone.utc)
    ws = sa.table("workspaces", sa.column("id"), sa.column("name"), sa.column("invite_policy"), sa.column("created_by_id"), sa.column("created_at"), sa.column("updated_at"))
    wm = sa.table("workspace_members", sa.column("workspace_id"), sa.column("user_id"), sa.column("role"), sa.column("created_at"))
    repos = sa.table("repositories", sa.column("id"), sa.column("workspace_id"))
    logins = {r[0]: r[1] for r in bind.execute(sa.text("SELECT id, login FROM users")).all()}
    rows = [(int(u), int(r), str(role)) for u, r, role in bind.execute(sa.text("SELECT user_id, repository_id, role FROM repository_access")).all() if int(u) in logins]
    shared = 0

    def make(name: str, owner: int, members: list[tuple[int, str]], repo_ids: list[int]) -> None:
        wid = bind.execute(
            sa.insert(ws)
            .values(
                name=name[:100],
                invite_policy="admin",
                created_by_id=owner,
                created_at=now,
                updated_at=now,
            )
            .returning(ws.c.id)
        ).scalar_one()
        for uid, role in members:
            bind.execute(sa.insert(wm).values(workspace_id=wid, user_id=uid, role=role, created_at=now))
        for rid in repo_ids:
            bind.execute(sa.update(repos).where(repos.c.id == rid).values(workspace_id=wid))

    for g in group_legacy_access(rows):
        owner = next(u for u, r in g["members"] if r == "owner")
        if len(g["members"]) == 1:
            name = f"{logins[owner]}'s workspace"
        else:
            shared += 1
            name = f"Shared workspace {shared}"
        make(name, owner, g["members"], g["repository_ids"])
    member_ids = {r[0] for r in bind.execute(sa.text("SELECT user_id FROM workspace_members")).all()}
    for uid in sorted(set(logins) - member_ids):
        make(f"{logins[uid]}'s workspace", uid, [(uid, "owner")], [])


def downgrade() -> None:
    """Not supported: workspace membership has no representation in the old model. Restore from a backup instead."""
    raise NotImplementedError("0006 cannot be downgraded; restore a database backup")
