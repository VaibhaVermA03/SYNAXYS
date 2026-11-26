"""Pure workspace rules (no third-party imports; unit tested). The database layer (workspace_service.py) only applies what these functions decide.

Roles: owner (exactly one; manages everything incl. billing-like actions: delete workspace, change roles, transfer) > admin (manages repositories, invites
members) > member (views, requests reviews). On the repository level owner and admin are 'owner' (repository admin), member is 'member'."""
import hashlib
import re
import secrets
from datetime import datetime, timedelta

ROLES = ("owner", "admin", "member")
RANK = {"member": 1, "admin": 2, "owner": 3}
INVITE_ROLES = ("admin", "member")
INVITE_TTL = timedelta(days=7)
LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")  # GitHub login syntax
NAME_MAX = 100


def repo_role_for(workspace_role: str) -> str:
    """What a workspace role means on the repositories of that workspace (the existing RepositoryAccess vocabulary)."""
    return "owner" if workspace_role in ("owner", "admin") else "member"


def has_role(actual: str | None, minimum: str) -> bool:
    return actual is not None and RANK.get(actual, 0) >= RANK[minimum]


def clean_name(name: str | None) -> str | None:
    n = " ".join((name or "").split())
    return n if 1 <= len(n) <= NAME_MAX else None


def normalize_login(login: str | None) -> str | None:
    l = (login or "").strip().lstrip("@")
    return l.lower() if LOGIN_RE.fullmatch(l) else None


def can_invite(actor_role: str | None, invite_policy: str, invitee_role: str) -> str | None:
    """None = allowed, else a reason code."""
    if invitee_role not in INVITE_ROLES:
        return "invalid_role"
    if not has_role(actor_role, "owner" if invite_policy == "owner" else "admin"):
        return "not_allowed"
    if invitee_role == "admin" and actor_role != "owner":
        return "only_owner_invites_admins"
    return None


def can_remove(actor_role: str | None, target_role: str, *, same_user: bool) -> str | None:
    if same_user:
        return "use_leave"
    if target_role == "owner":
        return "cannot_remove_owner"
    if actor_role == "owner":
        return None
    if actor_role == "admin" and target_role == "member":
        return None
    return "not_allowed"


def can_change_role(actor_role: str | None, target_role: str, new_role: str, *, same_user: bool) -> str | None:
    if actor_role != "owner":
        return "only_owner"
    if same_user:
        return "cannot_change_own_role"
    if target_role == "owner" or new_role == "owner":
        return "use_transfer"  # ownership only moves through an explicit transfer
    return None if new_role in INVITE_ROLES else "invalid_role"


def new_invitation_token() -> tuple[str, str]:
    """(token shown once, sha256 stored)."""
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def hash_invitation_token(raw: str) -> str:
    return hashlib.sha256((raw or "").encode()).hexdigest()


def invitation_state(status: str, expires_at: datetime, now: datetime) -> str:
    """Effective status: a pending invitation past its expiry is 'expired' even before a cleanup job marks it."""
    return "expired" if status == "pending" and expires_at <= now else status


def accept_blocker(*, state: str, invited_login: str, user_login: str, already_member: bool) -> str | None:
    if state != "pending":
        return {"accepted": "already_accepted", "revoked": "revoked", "expired": "expired"}.get(state, "not_pending")
    if invited_login.lower() != user_login.lower():
        return "wrong_user"  # a forwarded link is useless to anyone else
    if already_member:
        return "already_member"
    return None


def pick_successor(members: list[dict]) -> dict | None:
    """Who inherits a workspace when its owner is deleted: the longest-standing admin, else the longest-standing member. members: {user_id, role, joined (sortable)}."""
    for role in ("admin", "member"):
        c = sorted((m for m in members if m["role"] == role), key=lambda m: (m["joined"], m["user_id"]))
        if c:
            return c[0]
    return None


def group_legacy_access(rows: list[tuple[int, int, str]]) -> list[dict]:
    """Migration helper. rows: (user_id, repository_id, role) from the pre-workspace repository_access table. Repositories whose set of (user, role)
    pairs is IDENTICAL share one workspace, so every user keeps exactly the repositories they could see before (nobody gains access).
    Returns [{members: [(user_id, workspace_role)], repository_ids: [...]}] with deterministic order. The first 'owner' (lowest id) becomes the workspace
    owner, other owners become admins, members stay members; a group without any owner makes its lowest user id the owner (someone must own it)."""
    by_repo: dict[int, set[tuple[int, str]]] = {}
    for uid, rid, role in rows:
        by_repo.setdefault(rid, set()).add((uid, role))
    groups: dict[frozenset, list[int]] = {}
    for rid in sorted(by_repo):
        groups.setdefault(frozenset(by_repo[rid]), []).append(rid)
    out = []
    for key, rids in sorted(groups.items(), key=lambda kv: min(kv[1])):
        users = sorted(key)
        owners = [u for u, r in users if r == "owner"]
        owner = owners[0] if owners else users[0][0]
        members = [(u, "owner" if u == owner else "admin" if r == "owner" else "member") for u, r in users]
        out.append({"members": members, "repository_ids": rids})
    return out


REAUTH_WINDOW = timedelta(minutes=15)


def _aware(dt: datetime) -> datetime:
    from datetime import timezone
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def deletion_blocker(user, session, confirm_login: str, now: datetime) -> str | None:
    """Identity check before account deletion: None = verified. Needs the typed login AND a session created within REAUTH_WINDOW
    (sessions are only created by a fresh GitHub sign-in, so a recent session proves a recent re-authentication)."""
    if user.github_id is not None and user.github_id < 0:
        return "demo_user"
    if (confirm_login or "").strip().lower() != user.login.lower():
        return "confirmation_mismatch"
    if now - _aware(session.created_at) > REAUTH_WINDOW:
        return "reauth_required"
    return None
