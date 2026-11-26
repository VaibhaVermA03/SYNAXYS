"""Workspaces, members, invitations and the derived repository access (Phase 4). All authorization decisions come from workspace_logic.py.

INVARIANT (kept by sync_access): for every repository that belongs to a workspace, repository_access contains exactly one row per workspace member
(role derived from the workspace role) and no other rows. Repositories without a workspace keep their GitHub-derived rows. Every existing query that
joins repository_access therefore automatically respects workspace boundaries."""
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequest, Conflict, Forbidden, NotFound, ValidationFailed
from app.db.base import utcnow
from app.models import AuditLog, Notification, Repository, RepositoryAccess, User, Workspace, WorkspaceInvitation, WorkspaceMember
from app.services import job_queue
from app.services import notification_service as notif
from app.services.workspace_logic import (INVITE_TTL, accept_blocker, can_change_role, can_invite, can_remove, clean_name, has_role, hash_invitation_token, invitation_state,
                                          new_invitation_token, normalize_login, repo_role_for)


def _aware(d):
    from app.services.auth_service import aware
    return aware(d)


def audit(db: Session, user_id: int | None, action: str, workspace_id: int | None, target_type: str | None = None, target_id=None, **meta) -> None:
    db.add(AuditLog(user_id=user_id, workspace_id=workspace_id, action=action, target_type=target_type, target_id=str(target_id) if target_id is not None else None, meta=meta or None))


# ---- lookup + authorization --------------------------------------------------------------------------------------
def get_membership(db: Session, user_id: int, workspace_id: int) -> WorkspaceMember | None:
    return db.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id))


def require_member(db: Session, user: User, workspace_id: int, minimum: str = "member") -> tuple[Workspace, WorkspaceMember]:
    """Non-members get 404 (a workspace's existence is not revealed); members with too low a role get 403."""
    m = get_membership(db, user.id, workspace_id)
    ws = db.get(Workspace, workspace_id) if m else None
    if m is None or ws is None:
        raise NotFound("Workspace not found")
    if not has_role(m.role, minimum):
        raise Forbidden(f"{minimum.capitalize()} permission is required in this workspace")
    return ws, m


def list_for_user(db: Session, user: User) -> list[dict]:
    rows = db.execute(select(Workspace, WorkspaceMember.role).join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
                      .where(WorkspaceMember.user_id == user.id).order_by(Workspace.name, Workspace.id)).all()
    ids = [w.id for w, _ in rows]
    members = dict(db.execute(select(WorkspaceMember.workspace_id, func.count()).where(WorkspaceMember.workspace_id.in_(ids or [0])).group_by(WorkspaceMember.workspace_id)).all())
    repos = dict(db.execute(select(Repository.workspace_id, func.count()).where(Repository.workspace_id.in_(ids or [0])).group_by(Repository.workspace_id)).all())
    return [{"id": w.id, "name": w.name, "role": role, "invite_policy": w.invite_policy, "members": members.get(w.id, 0), "repositories": repos.get(w.id, 0)} for w, role in rows]


def ensure_personal_workspace(db: Session, user: User) -> Workspace | None:
    """Every user belongs to at least one workspace (created at first sign-in). Returns the new workspace or None."""
    if db.scalar(select(WorkspaceMember.id).where(WorkspaceMember.user_id == user.id).limit(1)) is not None:
        return None
    return create_workspace(db, user, f"{user.login}'s workspace", commit=False)


def default_workspace_id(db: Session, user: User) -> int | None:
    """The user's workspace when it is unambiguous (exactly one)."""
    ids = db.scalars(select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user.id)).all()
    return ids[0] if len(ids) == 1 else None


# ---- derived repository access ------------------------------------------------------------------------------------
def sync_access(db: Session, workspace_id: int) -> None:
    """Make repository_access match membership for ALL repositories of the workspace. Idempotent; does not commit."""
    repo_ids = db.scalars(select(Repository.id).where(Repository.workspace_id == workspace_id)).all()
    if not repo_ids:
        return
    want = {uid: repo_role_for(role) for uid, role in db.execute(select(WorkspaceMember.user_id, WorkspaceMember.role).where(WorkspaceMember.workspace_id == workspace_id))}
    have = {(a.user_id, a.repository_id): a for a in db.scalars(select(RepositoryAccess).where(RepositoryAccess.repository_id.in_(repo_ids))).all()}
    for (uid, rid), a in have.items():
        if uid not in want:
            db.delete(a)
        elif a.role != want[uid]:
            a.role = want[uid]
    for rid in repo_ids:
        for uid, role in want.items():
            if (uid, rid) not in have:
                db.add(RepositoryAccess(user_id=uid, repository_id=rid, role=role))
    db.flush()


def assign_repository(db: Session, user: User, repo: Repository, workspace_id: int) -> None:
    """Connect a repository to a workspace. The caller must already be GitHub-admin on the repo (get_repo_for_user(require_owner)) and workspace admin here."""
    require_member(db, user, workspace_id, "admin")
    if repo.workspace_id is not None and repo.workspace_id != workspace_id:
        raise Conflict("This repository already belongs to another workspace.", code="repository_in_other_workspace")
    if repo.workspace_id is None:
        repo.workspace_id = workspace_id
        audit(db, user.id, "workspace.repository_added", workspace_id, "repository", repo.id)
    db.flush()
    sync_access(db, workspace_id)


# ---- workspaces ---------------------------------------------------------------------------------------------------
def create_workspace(db: Session, user: User, name: str, *, commit: bool = True) -> Workspace:
    n = clean_name(name)
    if n is None:
        raise ValidationFailed("Invalid name", fields=[{"loc": ["name"], "msg": "Name must be 1-100 characters"}])
    ws = Workspace(name=n, created_by_id=user.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner"))
    audit(db, user.id, "workspace.create", ws.id, "workspace", ws.id)
    if commit:
        db.commit()
    return ws


def update_workspace(db: Session, user: User, workspace_id: int, *, name: str | None, invite_policy: str | None) -> Workspace:
    ws, m = require_member(db, user, workspace_id, "admin")
    changes = {}
    if name is not None:
        n = clean_name(name)
        if n is None:
            raise ValidationFailed("Invalid name", fields=[{"loc": ["name"], "msg": "Name must be 1-100 characters"}])
        changes["name"], ws.name = n, n
    if invite_policy is not None:
        if m.role != "owner":
            raise Forbidden("Only the workspace owner can change who may invite")
        if invite_policy not in ("owner", "admin"):
            raise ValidationFailed("Invalid policy", fields=[{"loc": ["invite_policy"], "msg": "Must be owner or admin"}])
        changes["invite_policy"], ws.invite_policy = invite_policy, invite_policy
    if changes:
        audit(db, user.id, "workspace.update", ws.id, "workspace", ws.id, **changes)
        db.commit()
    return ws


def delete_workspace(db: Session, user: User, workspace_id: int, confirm_name: str) -> None:
    """Owner only; the name must be typed. Repositories are disconnected (index cleanup queued) and detached; their data is not read by anyone afterwards."""
    ws, _ = require_member(db, user, workspace_id, "owner")
    if (confirm_name or "").strip() != ws.name:
        raise BadRequest("Type the workspace name to confirm.", code="confirmation_mismatch")
    _dissolve(db, ws)
    audit(db, user.id, "workspace.delete", None, "workspace", workspace_id, name_length=len(ws.name))
    db.commit()


def _dissolve(db: Session, ws: Workspace) -> None:
    repos = db.scalars(select(Repository).where(Repository.workspace_id == ws.id)).all()
    for r in repos:
        r.is_enabled, r.workspace_id, r.index_status = False, None, "not_indexed"
        job_queue.enqueue_or_requeue(db, "index_delete", {"repository_id": r.id}, f"index_delete:{r.id}")
    db.flush()
    if repos:
        db.execute(delete(RepositoryAccess).where(RepositoryAccess.repository_id.in_([r.id for r in repos])))
    db.execute(update(AuditLog).where(AuditLog.workspace_id == ws.id).values(workspace_id=None))
    db.execute(delete(Notification).where(Notification.workspace_id == ws.id))
    db.execute(delete(WorkspaceInvitation).where(WorkspaceInvitation.workspace_id == ws.id))
    db.execute(delete(WorkspaceMember).where(WorkspaceMember.workspace_id == ws.id))  # explicit: portable even where foreign-key cascades are not enforced
    db.execute(delete(Workspace).where(Workspace.id == ws.id))
    db.expire_all()
    db.flush()


# ---- members ------------------------------------------------------------------------------------------------------
def list_members(db: Session, user: User, workspace_id: int) -> list[dict]:
    require_member(db, user, workspace_id)
    rows = db.execute(select(WorkspaceMember, User).join(User, User.id == WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == workspace_id)
                      .order_by(WorkspaceMember.created_at, WorkspaceMember.id)).all()
    return [{"user_id": m.user_id, "login": u.login, "name": u.name, "avatar_url": u.avatar_url, "role": m.role, "joined_at": m.created_at.isoformat()} for m, u in rows]


def change_role(db: Session, user: User, workspace_id: int, target_user_id: int, new_role: str) -> None:
    ws, me = require_member(db, user, workspace_id)
    target = get_membership(db, target_user_id, workspace_id)
    if target is None:
        raise NotFound("Member not found")
    reason = can_change_role(me.role, target.role, new_role, same_user=target.user_id == user.id)
    if reason:
        raise Forbidden(_REASONS.get(reason, "Not allowed"))
    old, target.role = target.role, new_role
    db.flush()
    sync_access(db, workspace_id)
    audit(db, user.id, "workspace.role_changed", workspace_id, "user", target_user_id, old=old, new=new_role)
    notif.safe(notif.notify, db, [target_user_id], kind="workspace_role_changed", title=f"Your role in “{ws.name}” is now {new_role}", link="/app/settings/workspaces",
               workspace_id=ws.id, dedup_key=f"ws:{ws.id}:role:{target_user_id}:{new_role}:{utcnow().timestamp():.0f}")
    db.commit()


def remove_member(db: Session, user: User, workspace_id: int, target_user_id: int) -> None:
    ws, me = require_member(db, user, workspace_id)
    target = get_membership(db, target_user_id, workspace_id)
    if target is None:
        raise NotFound("Member not found")
    reason = can_remove(me.role, target.role, same_user=target.user_id == user.id)
    if reason:
        raise Forbidden(_REASONS.get(reason, "Not allowed"))
    _drop_member(db, ws, target)
    audit(db, user.id, "workspace.member_removed", workspace_id, "user", target_user_id)
    notif.safe(notif.notify, db, [target_user_id], kind="workspace_removed", title=f"You were removed from “{ws.name}”", workspace_id=None,
               dedup_key=f"ws:{ws.id}:removed:{target_user_id}:{utcnow().timestamp():.0f}")
    db.commit()


def leave(db: Session, user: User, workspace_id: int) -> None:
    ws, me = require_member(db, user, workspace_id)
    if me.role == "owner":
        raise Conflict("Transfer ownership to another member (or delete the workspace) before leaving.", code="owner_cannot_leave")
    _drop_member(db, ws, me)
    audit(db, user.id, "workspace.member_left", workspace_id, "user", user.id)
    notif.safe(notif.notify, db, notif_owner_ids(db, ws.id), kind="workspace_member_left", title=f"{user.login} left “{ws.name}”", link="/app/settings/workspaces", workspace_id=ws.id,
               dedup_key=f"ws:{ws.id}:left:{user.id}:{utcnow().timestamp():.0f}")
    db.commit()


def _drop_member(db: Session, ws: Workspace, member: WorkspaceMember) -> None:
    db.delete(member)
    db.flush()
    sync_access(db, ws.id)


def notif_owner_ids(db: Session, workspace_id: int) -> set[int]:
    return {u for (u,) in db.execute(select(WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role.in_(["owner", "admin"])))}


def transfer_ownership(db: Session, user: User, workspace_id: int, new_owner_id: int) -> None:
    ws, me = require_member(db, user, workspace_id, "owner")
    target = get_membership(db, new_owner_id, workspace_id)
    if target is None or target.user_id == user.id:
        raise NotFound("Member not found")
    target.role, me.role = "owner", "admin"
    sync_access(db, workspace_id)
    audit(db, user.id, "workspace.ownership_transferred", workspace_id, "user", new_owner_id)
    notif.safe(notif.notify, db, [new_owner_id], kind="workspace_owner", title=f"You are now the owner of “{ws.name}”", link="/app/settings/workspaces", workspace_id=ws.id,
               dedup_key=f"ws:{ws.id}:owner:{new_owner_id}:{utcnow().timestamp():.0f}")
    db.commit()


_REASONS = {"use_leave": "Use “Leave workspace” to remove yourself.", "cannot_remove_owner": "The owner cannot be removed; transfer ownership first.", "not_allowed": "You are not allowed to do this.",
            "only_owner": "Only the workspace owner can change roles.", "cannot_change_own_role": "You cannot change your own role.", "use_transfer": "Ownership only moves through “Transfer ownership”.",
            "invalid_role": "Invalid role.", "only_owner_invites_admins": "Only the owner can invite admins."}


# ---- invitations --------------------------------------------------------------------------------------------------
def create_invitation(db: Session, user: User, workspace_id: int, login: str, role: str) -> tuple[WorkspaceInvitation, str]:
    """Returns (invitation, token). The token is returned ONCE (it is stored only as a hash) and goes into the invitation link."""
    ws, me = require_member(db, user, workspace_id)
    reason = can_invite(me.role, ws.invite_policy, role)
    if reason:
        raise Forbidden(_REASONS.get(reason, "Not allowed"))
    norm = normalize_login(login)
    if norm is None:
        raise ValidationFailed("Invalid GitHub login", fields=[{"loc": ["login"], "msg": "Enter a valid GitHub username"}])
    existing_user = db.scalar(select(User).where(func.lower(User.login) == norm))
    if existing_user is not None and get_membership(db, existing_user.id, workspace_id) is not None:
        raise Conflict("This person is already a member.", code="already_member")
    now = utcnow()
    pending = db.scalar(select(WorkspaceInvitation).where(WorkspaceInvitation.workspace_id == workspace_id, WorkspaceInvitation.invited_login == norm, WorkspaceInvitation.status == "pending"))
    if pending is not None:
        if _aware(pending.expires_at) > now:
            raise Conflict("There is already a pending invitation for this person. Revoke it to send a new one.", code="invitation_pending")
        pending.status, pending.responded_at = "expired", now
    raw, hashed = new_invitation_token()
    inv = WorkspaceInvitation(workspace_id=workspace_id, invited_login=norm, role=role, token_hash=hashed, invited_by_id=user.id, expires_at=now + INVITE_TTL)
    db.add(inv)
    db.flush()
    audit(db, user.id, "workspace.invitation_created", workspace_id, "invitation", inv.id, role=role)
    if existing_user is not None:
        notif.safe(notif.notify, db, [existing_user.id], kind="workspace_invitation", title=f"{user.login} invited you to “{ws.name}” as {role}", body="Open the invitation to accept or ignore it.",
                   link="/app/settings/workspaces", dedup_key=f"invitation:{inv.id}")
    db.commit()
    return inv, raw


def list_invitations(db: Session, user: User, workspace_id: int) -> list[dict]:
    require_member(db, user, workspace_id, "admin")
    now = utcnow()
    rows = db.scalars(select(WorkspaceInvitation).where(WorkspaceInvitation.workspace_id == workspace_id).order_by(WorkspaceInvitation.id.desc()).limit(100)).all()
    return [_inv_out(i, invitation_state(i.status, _aware(i.expires_at), now)) for i in rows]


def _inv_out(i: WorkspaceInvitation, state: str) -> dict:
    return {"id": i.id, "login": i.invited_login, "role": i.role, "status": state, "expires_at": i.expires_at.isoformat(), "created_at": i.created_at.isoformat()}


def revoke_invitation(db: Session, user: User, workspace_id: int, invitation_id: int) -> None:
    require_member(db, user, workspace_id, "admin")
    inv = db.get(WorkspaceInvitation, invitation_id)
    if inv is None or inv.workspace_id != workspace_id:
        raise NotFound("Invitation not found")  # an id from another workspace is simply not found
    if inv.status != "pending":
        raise Conflict("Only pending invitations can be revoked.", code="not_pending")
    inv.status, inv.responded_at = "revoked", utcnow()
    audit(db, user.id, "workspace.invitation_revoked", workspace_id, "invitation", inv.id)
    db.commit()


def my_invitations(db: Session, user: User) -> list[dict]:
    """Pending, unexpired invitations addressed to my GitHub login (the token is never returned here)."""
    now = utcnow()
    rows = db.execute(select(WorkspaceInvitation, Workspace.name).join(Workspace, Workspace.id == WorkspaceInvitation.workspace_id)
                      .where(WorkspaceInvitation.invited_login == user.login.lower(), WorkspaceInvitation.status == "pending")).all()
    return [{**_inv_out(i, "pending"), "workspace_id": i.workspace_id, "workspace_name": name} for i, name in rows if _aware(i.expires_at) > now]


def accept_invitation(db: Session, user: User, token: str) -> Workspace:
    inv = db.scalar(select(WorkspaceInvitation).where(WorkspaceInvitation.token_hash == hash_invitation_token(token)))
    if inv is None:
        raise NotFound("Invitation not found")
    state = invitation_state(inv.status, _aware(inv.expires_at), utcnow())
    blocker = accept_blocker(state=state, invited_login=inv.invited_login, user_login=user.login, already_member=get_membership(db, user.id, inv.workspace_id) is not None)
    if blocker == "wrong_user":
        raise NotFound("Invitation not found")  # do not reveal that the token is valid for somebody else
    if blocker:
        raise Conflict({"expired": "This invitation has expired.", "revoked": "This invitation was revoked.", "already_accepted": "This invitation was already used.",
                        "already_member": "You are already a member of this workspace."}.get(blocker, "This invitation cannot be accepted."), code=blocker)
    ws = db.get(Workspace, inv.workspace_id)
    now = utcnow()
    res = db.execute(update(WorkspaceInvitation).where(WorkspaceInvitation.id == inv.id, WorkspaceInvitation.status == "pending")
                     .values(status="accepted", accepted_by_id=user.id, responded_at=now))
    if res.rowcount != 1:  # a concurrent accept won
        db.rollback()
        raise Conflict("This invitation was already used.", code="already_accepted")
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=inv.role, invited_by_id=inv.invited_by_id))
    db.flush()
    sync_access(db, ws.id)
    audit(db, user.id, "workspace.member_joined", ws.id, "user", user.id, role=inv.role)
    notif.safe(notif.notify, db, notif_owner_ids(db, ws.id) - {user.id}, kind="workspace_member_joined", title=f"{user.login} joined “{ws.name}”", link="/app/settings/workspaces",
               workspace_id=ws.id, dedup_key=f"ws:{ws.id}:joined:{user.id}:{inv.id}")
    db.commit()
    return ws


def decline_my_invitation(db: Session, user: User, invitation_id: int) -> None:
    inv = db.get(WorkspaceInvitation, invitation_id)
    if inv is None or inv.invited_login != user.login.lower() or inv.status != "pending":
        raise NotFound("Invitation not found")
    inv.status, inv.responded_at = "revoked", utcnow()
    audit(db, user.id, "workspace.invitation_declined", inv.workspace_id, "invitation", inv.id)
    db.commit()


def notify_pending_invitations(db: Session, user: User) -> None:
    """At sign-in: people invited before they had an account get their notification now (deduplicated)."""
    for i in my_invitations(db, user):
        notif.safe(notif.notify, db, [user.id], kind="workspace_invitation", title=f"You were invited to “{i['workspace_name']}” as {i['role']}", body="Open the invitation to accept or ignore it.",
                   link="/app/settings/workspaces", dedup_key=f"invitation:{i['id']}")


def workspace_audit(db: Session, user: User, workspace_id: int, limit: int = 100) -> list[dict]:
    """Workspace-level history: explicit workspace events plus repository/review/comment/finding events of this workspace's repositories."""
    require_member(db, user, workspace_id, "admin")
    from sqlalchemy import String, cast, or_
    from app.models import CodeReview, PullRequest
    repo_ids = select(cast(Repository.id, String)).where(Repository.workspace_id == workspace_id)
    review_ids = select(cast(CodeReview.id, String)).join(PullRequest, PullRequest.id == CodeReview.pull_request_id).join(Repository, Repository.id == PullRequest.repository_id).where(Repository.workspace_id == workspace_id)
    q = select(AuditLog, User.login).outerjoin(User, User.id == AuditLog.user_id).where(or_(
        AuditLog.workspace_id == workspace_id,
        (AuditLog.target_type == "repository") & AuditLog.target_id.in_(repo_ids),
        (AuditLog.target_type == "review") & AuditLog.target_id.in_(review_ids)))
    rows = db.execute(q.order_by(AuditLog.id.desc()).limit(min(limit, 200))).all()
    return [{"id": a.id, "action": a.action, "actor": login, "target_type": a.target_type, "target_id": a.target_id, "created_at": a.created_at.isoformat()} for a, login in rows]
