"""Account data export and account deletion (Phase 4).

EXPORT: a ZIP of JSON files built by a background job, stored in `data_exports` (not on disk), downloadable only by its owner through an authenticated endpoint,
expiring after EXPORT_TTL_HOURS. Included: profile, workspace memberships (member lists only where the user is owner/admin), the user's review rules, notifications,
the user's own audit trail, and review history + findings + comments of repositories the user can access. NEVER included: tokens, session data, invitation tokens,
other users' e-mail addresses or private data (other people appear only as the GitHub handles already visible in the shared workspace).

DELETION: identity is re-verified (typed login + a session younger than 15 minutes), shared workspaces survive (ownership is handed to the longest-standing admin/member),
a workspace with no other member is dissolved (repositories disconnected, vectors removed by the queue), credentials and sessions are deleted, the user row is removed and
references in shared data are cleared. The audit trail keeps only an anonymous `account.deleted` event."""
import io
import json
import zipfile
from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequest, Conflict, Forbidden
from app.db.base import utcnow
from app.models import (AuditLog, CodeReview, DataExport, GitHubInstallation, Notification, OAuthIdentity, PullRequest, Repository, RepositoryAccess,
                        ReviewComment, ReviewFinding, ReviewPostingAttempt, ReviewRule, User, UserSession, Workspace, WorkspaceInvitation, WorkspaceMember)
from app.services import job_queue
from app.services import notification_service as notif
from app.services import workspace_service as ws_svc
from app.services.auth_service import aware
from app.services.workspace_logic import deletion_blocker, pick_successor

MAX_ROWS = 5000
MAX_BYTES = 40_000_000


# ---- export ----------------------------------------------------------------------------------------------------------
def request_export(db: Session, user: User, ttl_hours: int) -> DataExport:
    active = db.scalar(select(DataExport).where(DataExport.user_id == user.id, DataExport.status == "pending"))
    if active is not None:
        raise Conflict("An export is already being prepared.", code="export_pending")
    ex = DataExport(user_id=user.id, status="pending", expires_at=utcnow() + timedelta(hours=ttl_hours))
    db.add(ex)
    db.flush()
    job_queue.enqueue(db, "account_export", {"export_id": ex.id}, f"account_export:{ex.id}", timeout_seconds=900)
    db.add(AuditLog(user_id=user.id, action="account.export_requested", target_type="export", target_id=str(ex.id)))
    db.commit()
    return ex


def build_export(db: Session, user: User) -> bytes:
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    repo_ids = select(RepositoryAccess.repository_id).where(RepositoryAccess.user_id == user.id)
    files: dict[str, object] = {}
    files["profile.json"] = {"id": user.id, "github_id": user.github_id, "login": user.login, "name": user.name, "email": user.email, "avatar_url": user.avatar_url, "created_at": iso(user.created_at)}
    memberships = db.execute(select(WorkspaceMember, Workspace).join(Workspace, Workspace.id == WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user.id)).all()
    wsout = []
    for m, w in memberships:
        entry = {"workspace_id": w.id, "name": w.name, "my_role": m.role, "joined_at": iso(m.created_at), "member_count": db.scalar(select(func.count()).select_from(WorkspaceMember).where(WorkspaceMember.workspace_id == w.id))}
        if m.role in ("owner", "admin"):  # members' GitHub handles only for people who can already see them in the app
            entry["members"] = [{"login": u.login, "role": mm.role} for mm, u in db.execute(select(WorkspaceMember, User).join(User, User.id == WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == w.id))]
        wsout.append(entry)
    files["workspaces.json"] = wsout
    files["settings.json"] = {"review_rules": [{"name": r.name, "severity": r.severity, "instruction": r.instruction, "languages": r.languages, "file_patterns": r.file_patterns, "enabled": r.enabled,
                                               "repository_id": r.repository_id} for r in db.scalars(select(ReviewRule).where(ReviewRule.owner_user_id == user.id)).all()]}
    files["activity.json"] = [{"action": a.action, "target_type": a.target_type, "target_id": a.target_id, "created_at": iso(a.created_at)}
                              for a in db.scalars(select(AuditLog).where(AuditLog.user_id == user.id).order_by(AuditLog.id.desc()).limit(MAX_ROWS)).all()]
    files["notifications.json"] = [{"kind": n.kind, "title": n.title, "body": n.body, "read": n.read_at is not None, "created_at": iso(n.created_at)}
                                   for n in db.scalars(select(Notification).where(Notification.user_id == user.id).order_by(Notification.id.desc()).limit(MAX_ROWS)).all()]
    reviews = db.execute(select(CodeReview, PullRequest, Repository).join(PullRequest, PullRequest.id == CodeReview.pull_request_id).join(Repository, Repository.id == PullRequest.repository_id)
                         .where(Repository.id.in_(repo_ids), CodeReview.is_demo.is_(False)).order_by(CodeReview.id.desc()).limit(MAX_ROWS)).all()
    rv_ids = [r.id for r, _, _ in reviews]
    files["reviews.json"] = [{"id": r.id, "repository": repo.full_name, "pull_request": pr.number, "pull_request_title": pr.title, "status": r.status, "trigger": r.trigger, "summary": r.summary,
                              "commit": r.head_sha, "created_at": iso(r.created_at), "finished_at": iso(r.finished_at), "requested_by_me": r.requested_by_id == user.id} for r, pr, repo in reviews]
    findings = db.scalars(select(ReviewFinding).where(ReviewFinding.review_id.in_(rv_ids or [0])).order_by(ReviewFinding.id.desc()).limit(MAX_ROWS)).all()
    files["findings.json"] = [{"id": f.id, "review_id": f.review_id, "severity": f.severity, "category": f.category, "title": f.title, "path": f.path, "start_line": f.start_line, "end_line": f.end_line,
                               "explanation": f.explanation, "remediation": f.remediation, "status": f.status, "dismissed_by_me": f.dismissed_by_id == user.id, "dismiss_reason": f.dismiss_reason} for f in findings]
    comments = db.execute(select(ReviewComment, ReviewFinding.review_id).join(ReviewFinding, ReviewFinding.id == ReviewComment.finding_id).where(ReviewFinding.review_id.in_(rv_ids or [0]))
                          .limit(MAX_ROWS)).all()
    files["comments.json"] = [{"id": c.id, "review_id": rid, "state": c.state, "body": c.body, "edited": c.edited} for c, rid in comments]
    files["README.txt"] = ("SYNAXYS data export. Generated for your account only.\nIncluded: profile, workspace memberships, your review rules, your activity and notifications, and review history, "
                           "findings and comments of repositories you can access.\nNot included: credentials, tokens, sessions, other people's private data.\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content if isinstance(content, str) else json.dumps(content, indent=2, default=str))
    data = buf.getvalue()
    if len(data) > MAX_BYTES:
        raise ValueError("export too large")
    return data


def run_export_job(db: Session, export_id: int) -> None:
    ex = db.get(DataExport, export_id)
    if ex is None or ex.status != "pending":
        return
    user = db.get(User, ex.user_id)
    try:
        data = build_export(db, user)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        ex = db.get(DataExport, export_id)
        ex.status, ex.error = "failed", type(exc).__name__[:100]
        db.commit()
        notif.safe(notif.notify, db, [ex.user_id], kind="export_failed", title="Your data export failed", body="Please try again.", link="/app/settings/account", dedup_key=f"export:{ex.id}:failed")
        db.commit()
        return
    ex.payload, ex.size_bytes, ex.status = data, len(data), "ready"
    notif.safe(notif.notify, db, [ex.user_id], kind="export_ready", title="Your data export is ready", body="Download it from Account settings before it expires.", link="/app/settings/account", dedup_key=f"export:{ex.id}:ready")
    db.commit()


def get_export_for_download(db: Session, user: User, export_id: int) -> DataExport:
    from app.core.exceptions import NotFound
    ex = db.get(DataExport, export_id)
    if ex is None or ex.user_id != user.id:
        raise NotFound("Export not found")
    if ex.status != "ready" or ex.payload is None:
        raise Conflict("This export is not ready.", code="export_not_ready")
    if aware(ex.expires_at) <= utcnow():
        raise Conflict("This export has expired. Request a new one.", code="export_expired")
    ex.downloaded_at = utcnow()
    db.add(AuditLog(user_id=user.id, action="account.export_downloaded", target_type="export", target_id=str(ex.id)))
    db.commit()
    return ex


# ---- deletion --------------------------------------------------------------------------------------------------------
def delete_account(db: Session, user: User, session: UserSession, confirm_login: str, gh=None, s=None) -> dict:
    blocker = deletion_blocker(user, session, confirm_login, utcnow())
    if blocker == "reauth_required":
        raise Forbidden("For your security, sign in with GitHub again, then delete your account within 15 minutes.")  # frontend sends the user to /login
    if blocker:
        raise BadRequest("Type your GitHub username exactly to confirm." if blocker == "confirmation_mismatch" else "Demo accounts cannot be deleted.", code=blocker)
    uid = user.id
    stats = {"workspaces_dissolved": 0, "ownership_transferred": 0, "memberships_removed": 0}
    token_revoked = _revoke_remote(db, user, gh, s)
    for m in db.scalars(select(WorkspaceMember).where(WorkspaceMember.user_id == uid)).all():
        ws = db.get(Workspace, m.workspace_id)
        others = [{"user_id": o.user_id, "role": o.role, "joined": o.created_at} for o in db.scalars(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws.id, WorkspaceMember.user_id != uid)).all()]
        if m.role == "owner":
            heir = pick_successor(others)
            if heir is None:
                ws_svc._dissolve(db, ws)  # nobody else is in it: nothing shared is lost
                stats["workspaces_dissolved"] += 1
                continue
            db.execute(update(WorkspaceMember).where(WorkspaceMember.workspace_id == ws.id, WorkspaceMember.user_id == heir["user_id"]).values(role="owner"))
            notif.safe(notif.notify, db, [heir["user_id"]], kind="workspace_owner", title=f"You are now the owner of “{ws.name}”", body="The previous owner deleted their account.", link="/app/settings/workspaces",
                       workspace_id=ws.id, dedup_key=f"ws:{ws.id}:owner:{heir['user_id']}:inherit")
            stats["ownership_transferred"] += 1
        db.delete(m)
        db.flush()
        ws_svc.sync_access(db, ws.id)
        stats["memberships_removed"] += 1
    # references in shared data are cleared (portable: also on databases without enforced foreign keys)
    db.execute(update(CodeReview).where(CodeReview.requested_by_id == uid).values(requested_by_id=None))
    db.execute(update(CodeReview).where(CodeReview.cancelled_by_id == uid).values(cancelled_by_id=None))
    db.execute(update(ReviewFinding).where(ReviewFinding.dismissed_by_id == uid).values(dismissed_by_id=None))
    db.execute(update(ReviewComment).where(ReviewComment.approved_by_id == uid).values(approved_by_id=None))
    db.execute(update(ReviewComment).where(ReviewComment.github_deleted_by_id == uid).values(github_deleted_by_id=None))
    db.execute(update(ReviewPostingAttempt).where(ReviewPostingAttempt.actor_user_id == uid).values(actor_user_id=None))
    db.execute(update(AuditLog).where(AuditLog.user_id == uid).values(user_id=None))
    db.execute(update(GitHubInstallation).where(GitHubInstallation.owner_user_id == uid).values(owner_user_id=None))
    db.execute(update(WorkspaceMember).where(WorkspaceMember.invited_by_id == uid).values(invited_by_id=None))
    db.execute(update(WorkspaceInvitation).where(WorkspaceInvitation.invited_by_id == uid).values(invited_by_id=None))
    db.execute(update(WorkspaceInvitation).where(WorkspaceInvitation.accepted_by_id == uid).values(accepted_by_id=None))
    db.execute(update(Workspace).where(Workspace.created_by_id == uid).values(created_by_id=None))
    db.execute(delete(WorkspaceInvitation).where(WorkspaceInvitation.invited_login == user.login.lower(), WorkspaceInvitation.status == "pending"))
    db.execute(delete(ReviewRule).where(ReviewRule.owner_user_id == uid))
    db.execute(delete(RepositoryAccess).where(RepositoryAccess.user_id == uid))
    db.execute(delete(Notification).where(Notification.user_id == uid))
    db.execute(delete(DataExport).where(DataExport.user_id == uid))
    db.execute(delete(OAuthIdentity).where(OAuthIdentity.user_id == uid))  # the stored (encrypted) GitHub token
    db.execute(delete(UserSession).where(UserSession.user_id == uid))  # includes the current session: the user is signed out
    db.execute(delete(User).where(User.id == uid))
    db.add(AuditLog(user_id=None, action="account.deleted", target_type="account", meta={**stats, "remote_token_revoked": token_revoked}))  # no identity data
    db.commit()
    return {**stats, "remote_token_revoked": token_revoked}


def _revoke_remote(db: Session, user: User, gh, s) -> bool:
    """Best effort: tell GitHub to revoke the user's OAuth token. Local deletion happens regardless."""
    if gh is None or s is None or not getattr(s, "github_oauth_configured", False):
        return False
    try:
        from app.core.encryption import decrypt_secret
        ident = db.scalar(select(OAuthIdentity).where(OAuthIdentity.user_id == user.id, OAuthIdentity.provider == "github"))
        if ident is None or not ident.access_token_enc:
            return False
        gh.revoke_user_token(decrypt_secret(ident.access_token_enc, s.encryption_key))
        return True
    except Exception:  # noqa: BLE001 - never block deletion on GitHub
        return False
