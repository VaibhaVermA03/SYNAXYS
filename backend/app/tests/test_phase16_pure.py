"""Phase 4 (batch 16), stdlib-only: workspace rules, legacy access conversion, invitation rules, account deletion identity check."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

from app.services.retention_policy import RetentionPolicy
from app.services.workspace_logic import (REAUTH_WINDOW, accept_blocker, can_change_role, can_invite, can_remove, clean_name, deletion_blocker, group_legacy_access, has_role, hash_invitation_token, invitation_state,
                                          new_invitation_token, normalize_login, pick_successor, repo_role_for)

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def test_roles_map_to_repository_roles_and_rank():
    assert repo_role_for("owner") == "owner" and repo_role_for("admin") == "owner" and repo_role_for("member") == "member"
    assert has_role("owner", "admin") and has_role("admin", "admin") and not has_role("member", "admin") and not has_role(None, "member")


def test_invite_permissions():
    assert can_invite("admin", "admin", "member") is None and can_invite("owner", "admin", "admin") is None
    assert can_invite("admin", "admin", "admin") == "only_owner_invites_admins"            # admins cannot mint admins
    assert can_invite("admin", "owner", "member") == "not_allowed"                         # workspace policy: owner-only invites
    assert can_invite("member", "admin", "member") == "not_allowed" and can_invite(None, "admin", "member") == "not_allowed"
    assert can_invite("owner", "admin", "owner") == "invalid_role"                         # ownership is never granted by invitation


def test_remove_and_role_change_rules():
    assert can_remove("owner", "admin", same_user=False) is None and can_remove("admin", "member", same_user=False) is None
    assert can_remove("admin", "admin", same_user=False) == "not_allowed" and can_remove("member", "member", same_user=False) == "not_allowed"
    assert can_remove("owner", "owner", same_user=False) == "cannot_remove_owner" and can_remove("owner", "member", same_user=True) == "use_leave"
    assert can_change_role("owner", "member", "admin", same_user=False) is None and can_change_role("admin", "member", "admin", same_user=False) == "only_owner"
    assert can_change_role("owner", "member", "member", same_user=True) == "cannot_change_own_role"
    assert can_change_role("owner", "member", "owner", same_user=False) == "use_transfer" and can_change_role("owner", "owner", "admin", same_user=False) == "use_transfer"


def test_names_and_logins_are_validated():
    assert clean_name("  My   team ") == "My team" and clean_name("") is None and clean_name("x" * 101) is None and clean_name(None) is None
    assert normalize_login("@Octo-Cat") == "octo-cat" and normalize_login(" alice ") == "alice"
    for bad in (None, "", "-bad", "a b", "a/b", "x" * 40, "a;drop", "ünï"):
        assert normalize_login(bad) is None, bad


def test_invitation_tokens_are_random_hashed_and_expire():
    a, ha = new_invitation_token(); b, hb = new_invitation_token()
    assert a != b and len(a) >= 40 and ha == hash_invitation_token(a) and ha != hb and a not in ha
    assert invitation_state("pending", NOW + timedelta(days=1), NOW) == "pending" and invitation_state("pending", NOW, NOW) == "expired"
    assert invitation_state("accepted", NOW - timedelta(days=9), NOW) == "accepted"


def test_only_the_invited_github_user_can_accept():
    ok = dict(state="pending", invited_login="alice", user_login="Alice", already_member=False)
    assert accept_blocker(**ok) is None                                                    # login compare is case-insensitive
    assert accept_blocker(**{**ok, "user_login": "mallory"}) == "wrong_user"              # a forwarded link is useless to anybody else
    assert accept_blocker(**{**ok, "state": "expired"}) == "expired" and accept_blocker(**{**ok, "state": "revoked"}) == "revoked"
    assert accept_blocker(**{**ok, "state": "accepted"}) == "already_accepted" and accept_blocker(**{**ok, "already_member": True}) == "already_member"


def test_successor_is_the_longest_standing_admin_then_member():
    ms = [{"user_id": 5, "role": "member", "joined": 1}, {"user_id": 6, "role": "admin", "joined": 3}, {"user_id": 7, "role": "admin", "joined": 2}]
    assert pick_successor(ms)["user_id"] == 7
    assert pick_successor([m for m in ms if m["role"] == "member"])["user_id"] == 5 and pick_successor([]) is None


def test_legacy_access_conversion_never_widens_access():
    rows = [(1, 10, "owner"), (2, 10, "member"), (1, 11, "owner"), (2, 11, "member"),   # alice+bob share 10 and 11 identically -> one workspace
            (1, 12, "owner"),                                                           # alice alone on 12 -> her own workspace (bob must NOT get 12)
            (3, 13, "member"), (4, 13, "member")]                                       # nobody owns 13 -> lowest id becomes owner
    g = group_legacy_access(rows)
    assert [x["repository_ids"] for x in g] == [[10, 11], [12], [13]]
    assert g[0]["members"] == [(1, "owner"), (2, "member")] and g[1]["members"] == [(1, "owner")] and g[2]["members"] == [(3, "owner"), (4, "member")]
    seen = {}
    for grp in g:                                                                       # every user's visible repositories are exactly as before
        for uid, _ in grp["members"]:
            seen.setdefault(uid, set()).update(grp["repository_ids"])
    before = {}
    for uid, rid, _ in rows:
        before.setdefault(uid, set()).add(rid)
    assert seen == before
    two_owners = group_legacy_access([(1, 5, "owner"), (2, 5, "owner")])
    assert two_owners[0]["members"] == [(1, "owner"), (2, "admin")] and group_legacy_access([]) == []


def _user(github_id=5, login="Alice"): return NS(github_id=github_id, login=login)
def _sess(minutes_old): return NS(created_at=NOW - timedelta(minutes=minutes_old))


def test_account_deletion_needs_typed_login_and_a_fresh_session():
    assert deletion_blocker(_user(), _sess(3), "alice", NOW) is None                      # case-insensitive confirmation
    assert deletion_blocker(_user(), _sess(3), "bob", NOW) == "confirmation_mismatch" and deletion_blocker(_user(), _sess(3), "", NOW) == "confirmation_mismatch"
    assert deletion_blocker(_user(), _sess(16), "alice", NOW) == "reauth_required" and REAUTH_WINDOW == timedelta(minutes=15)
    assert deletion_blocker(_user(-1, "demo-user"), _sess(1), "demo-user", NOW) == "demo_user"


def test_retention_covers_invitations_exports_and_notifications():
    base = dict(retention_sessions_days=7, retention_webhook_days=30, retention_jobs_done_days=14, retention_jobs_failed_days=60, retention_indexing_jobs_days=30,
                retention_audit_days=365, retention_security_audit_days=730, cleanup_batch_size=500, cleanup_max_batches=20)
    c = RetentionPolicy.from_settings(NS(**base)).cutoffs(NOW)                          # settings objects without the new fields still work (defaults)
    assert c["invitations"] == NOW - timedelta(days=30) and c["notifications_read"] == NOW - timedelta(days=90) and c["notifications_any"] == NOW - timedelta(days=365)
    c2 = RetentionPolicy.from_settings(NS(**base, retention_invitations_days=0, retention_notifications_days=0, retention_notifications_max_days=0)).cutoffs(NOW)
    assert c2["invitations"] is None and c2["notifications_read"] is None
