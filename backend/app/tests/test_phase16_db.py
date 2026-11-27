"""Phase 4 (batch 16): workspaces, invitations, RBAC, derived repository access, notifications, data export, account deletion.
NOT RUN in the authoring sandbox (needs `pip install -r requirements-dev.txt`). Run: pytest -q app/tests/test_phase16_db.py"""
import io
import json
import zipfile

from sqlalchemy import select

from app.tests.conftest import login

H = lambda csrf: {"X-CSRF-Token": csrf}  # noqa: E731
BOB, CAROL = {"id": 2, "login": "bob"}, {"id": 3, "login": "carol"}


def setup_alice(ctx):
    """alice signs in, syncs her GitHub repo and connects it. Returns (client, csrf, repo_id, workspace_id)."""
    c, csrf = login(ctx)
    assert c.post("/api/v1/github/repositories/sync", headers=H(csrf)).status_code == 200
    repo = c.get("/api/v1/github/repositories").json()["items"][0]
    r = c.post(f"/api/v1/github/repositories/{repo['id']}/connect", headers=H(csrf))
    assert r.status_code == 200, r.text
    ws = c.get("/api/v1/workspaces").json()
    assert len(ws) == 1 and ws[0]["role"] == "owner"
    return c, csrf, repo["id"], ws[0]["id"]


def invite_and_accept(ctx, ac, acsrf, ws_id, who, role="member"):
    inv = ac.post(f"/api/v1/workspaces/{ws_id}/invitations", json={"login": who["login"], "role": role}, headers=H(acsrf))
    assert inv.status_code == 201, inv.text
    bc, bcsrf = login(ctx, who)
    r = bc.post("/api/v1/workspaces/invitations/accept", json={"token": inv.json()["token"]}, headers=H(bcsrf))
    assert r.status_code == 200, r.text
    return bc, bcsrf, inv.json()


def test_sign_in_creates_a_personal_workspace_and_connect_puts_the_repository_into_it(ctx):
    from app.models import AuditLog, Repository, RepositoryAccess
    c, csrf, repo_id, ws_id = setup_alice(ctx)
    with ctx.db() as db:
        assert db.get(Repository, repo_id).workspace_id == ws_id
        assert db.scalar(select(RepositoryAccess).where(RepositoryAccess.repository_id == repo_id)).role == "owner"
        assert db.scalar(select(AuditLog).where(AuditLog.action == "workspace.repository_added")).workspace_id == ws_id
    me = c.get("/api/v1/workspaces").json()[0]
    assert me["name"] == "alice's workspace" and me["members"] == 1 and me["repositories"] == 1


def test_invitation_grants_workspace_wide_access_only_to_the_invited_github_user(ctx):
    ac, acsrf, repo_id, ws_id = setup_alice(ctx)
    inv = ac.post(f"/api/v1/workspaces/{ws_id}/invitations", json={"login": "bob", "role": "member"}, headers=H(acsrf)).json()
    assert len(inv["token"]) >= 40 and "token" not in ac.get(f"/api/v1/workspaces/{ws_id}/invitations").json()[0]      # shown once, never listed
    cc, ccsrf = login(ctx, CAROL)
    assert cc.post("/api/v1/workspaces/invitations/accept", json={"token": inv["token"]}, headers=H(ccsrf)).status_code == 404   # forwarded link: useless
    assert cc.get("/api/v1/github/repositories").json()["items"] == []
    bc, bcsrf = login(ctx, BOB)
    assert [i["workspace_name"] for i in bc.get("/api/v1/workspaces/invitations/mine").json()] == ["alice's workspace"]
    assert bc.post("/api/v1/workspaces/invitations/accept", json={"token": inv["token"]}, headers=H(bcsrf)).status_code == 200
    assert bc.post("/api/v1/workspaces/invitations/accept", json={"token": inv["token"]}, headers=H(bcsrf)).json()["error"]["code"] in ("already_accepted", "already_member")
    items = bc.get("/api/v1/github/repositories").json()["items"]
    assert [i["full_name"] for i in items] == ["alice/app"] and items[0]["role"] == "member"                         # member of the repository, not an admin
    assert bc.post(f"/api/v1/github/repositories/{repo_id}/connect", headers=H(bcsrf)).status_code in (403, 404)       # members cannot manage repositories
    assert {m["login"]: m["role"] for m in ac.get(f"/api/v1/workspaces/{ws_id}/members").json()} == {"alice": "owner", "bob": "member"}


def test_non_members_cannot_see_or_touch_a_workspace_or_its_data(ctx):
    ac, acsrf, repo_id, ws_id = setup_alice(ctx)
    cc, ccsrf = login(ctx, CAROL)
    for method, path, body in [("get", f"/api/v1/workspaces/{ws_id}/members", None), ("get", f"/api/v1/workspaces/{ws_id}/invitations", None), ("get", f"/api/v1/workspaces/{ws_id}/audit", None),
                               ("patch", f"/api/v1/workspaces/{ws_id}", {"name": "x"}), ("post", f"/api/v1/workspaces/{ws_id}/invitations", {"login": "dave"}),
                               ("post", f"/api/v1/workspaces/{ws_id}/leave", None), ("post", f"/api/v1/workspaces/{ws_id}/transfer", {"user_id": 3}),
                               ("post", f"/api/v1/workspaces/{ws_id}/delete", {"confirm_name": "alice's workspace"})]:
        r = getattr(cc, method)(path, headers=H(ccsrf), **({"json": body} if body is not None else {}))
        assert r.status_code == 404, (path, r.status_code)                                                               # existence is not revealed
    assert cc.get("/api/v1/pull-requests", headers={"X-Workspace-Id": str(ws_id)}).status_code == 404                   # foreign workspace header is rejected


def test_roles_are_enforced_by_the_backend(ctx):
    ac, acsrf, repo_id, ws_id = setup_alice(ctx)
    bc, bcsrf, _ = invite_and_accept(ctx, ac, acsrf, ws_id, BOB, "member")
    assert bc.post(f"/api/v1/workspaces/{ws_id}/invitations", json={"login": "dave"}, headers=H(bcsrf)).status_code == 403          # members cannot invite
    assert bc.patch(f"/api/v1/workspaces/{ws_id}", json={"name": "hijack"}, headers=H(bcsrf)).status_code == 403
    assert bc.get(f"/api/v1/workspaces/{ws_id}/audit").status_code == 403
    bob_id = next(m["user_id"] for m in ac.get(f"/api/v1/workspaces/{ws_id}/members").json() if m["login"] == "bob")
    assert bc.patch(f"/api/v1/workspaces/{ws_id}/members/{bob_id}", json={"role": "admin"}, headers=H(bcsrf)).status_code == 403   # no self-promotion
    assert ac.patch(f"/api/v1/workspaces/{ws_id}/members/{bob_id}", json={"role": "admin"}, headers=H(acsrf)).status_code == 204
    assert bc.get("/api/v1/github/repositories").json()["items"][0]["role"] == "owner"                                              # admin = repository admin
    assert bc.post(f"/api/v1/workspaces/{ws_id}/invitations", json={"login": "dave", "role": "admin"}, headers=H(bcsrf)).status_code == 403   # only the owner invites admins
    assert bc.post(f"/api/v1/workspaces/{ws_id}/invitations", json={"login": "dave", "role": "member"}, headers=H(bcsrf)).status_code == 201
    assert ac.post(f"/api/v1/workspaces/{ws_id}/leave", headers=H(acsrf)).json()["error"]["code"] == "owner_cannot_leave"
    assert bc.post(f"/api/v1/workspaces/{ws_id}/delete", json={"confirm_name": "alice's workspace"}, headers=H(bcsrf)).status_code == 403   # only the owner deletes
    assert ac.post(f"/api/v1/workspaces/{ws_id}/transfer", json={"user_id": bob_id}, headers=H(acsrf)).status_code == 204
    assert {m["login"]: m["role"] for m in bc.get(f"/api/v1/workspaces/{ws_id}/members").json()} == {"alice": "admin", "bob": "owner"}


def test_removing_a_member_removes_repository_access_and_github_sync_does_not_restore_it(ctx):
    from app.models import RepositoryAccess
    ac, acsrf, repo_id, ws_id = setup_alice(ctx)
    bc, bcsrf, _ = invite_and_accept(ctx, ac, acsrf, ws_id, BOB)
    assert len(bc.get("/api/v1/github/repositories").json()["items"]) == 1
    bob_id = next(m["user_id"] for m in ac.get(f"/api/v1/workspaces/{ws_id}/members").json() if m["login"] == "bob")
    assert ac.delete(f"/api/v1/workspaces/{ws_id}/members/{bob_id}", headers=H(acsrf)).status_code == 204
    assert bc.get("/api/v1/github/repositories").json()["items"] == [] and bc.get(f"/api/v1/workspaces/{ws_id}/members").status_code == 404
    ctx.gh.user = BOB
    bc2, bcsrf2 = login(ctx, BOB)
    bc2.post("/api/v1/github/repositories/sync", headers=H(bcsrf2))                          # bob also sees the repo on GitHub in this fake: still no access
    assert bc2.get("/api/v1/github/repositories").json()["items"] == []
    with ctx.db() as db:
        assert {a.user_id for a in db.scalars(select(RepositoryAccess).where(RepositoryAccess.repository_id == repo_id)).all()} == {1}


def test_active_workspace_header_scopes_lists_and_only_for_members(ctx):
    ac, acsrf, repo_id, ws_id = setup_alice(ctx)
    other = ac.post("/api/v1/workspaces", json={"name": "Second"}, headers=H(acsrf)).json()
    assert len(ac.get("/api/v1/workspaces").json()) == 2
    assert len(ac.get("/api/v1/github/repositories", headers={"X-Workspace-Id": str(ws_id)}).json()["items"]) == 1
    assert ac.get("/api/v1/github/repositories", headers={"X-Workspace-Id": str(other["id"])}).json()["items"] == []     # nothing connected there
    assert ac.get("/api/v1/dashboard", headers={"X-Workspace-Id": str(other["id"])}).status_code == 200
    assert ac.get("/api/v1/github/repositories", headers={"X-Workspace-Id": "99999"}).status_code == 404
    assert ac.get("/api/v1/github/repositories", headers={"X-Workspace-Id": "abc"}).status_code == 404
    assert ac.post(f"/api/v1/github/repositories/{repo_id}/connect", json={"workspace_id": other["id"]}, headers=H(acsrf)).status_code == 200   # already in ws_id: stays there
    with ctx.db() as db:
        from app.models import Repository
        assert db.get(Repository, repo_id).workspace_id == ws_id


def test_workspace_delete_needs_the_name_and_detaches_repositories(ctx):
    from app.models import BackgroundJob, Repository
    ac, acsrf, repo_id, ws_id = setup_alice(ctx)
    assert ac.post(f"/api/v1/workspaces/{ws_id}/delete", json={"confirm_name": "wrong"}, headers=H(acsrf)).json()["error"]["code"] == "confirmation_mismatch"
    assert ac.post(f"/api/v1/workspaces/{ws_id}/delete", json={"confirm_name": "alice's workspace"}, headers=H(acsrf)).status_code == 204
    from app.models import PullRequest
    with ctx.db() as db:
        assert db.get(Repository, repo_id) is None and db.scalar(select(PullRequest.id)) is None                          # SYNAXYS data about the repository is gone, not just detached
        job = db.scalar(select(BackgroundJob).where(BackgroundJob.kind == "index_delete"))
        assert job is not None and job.payload == {"repository_id": repo_id, "purged": True}                             # vectors are removed through the queue
    assert ac.get("/api/v1/github/repositories").json()["items"] == []


def test_workspace_audit_lists_workspace_and_repository_events_for_admins(ctx):
    ac, acsrf, repo_id, ws_id = setup_alice(ctx)
    invite_and_accept(ctx, ac, acsrf, ws_id, BOB)
    actions = [e["action"] for e in ac.get(f"/api/v1/workspaces/{ws_id}/audit").json()]
    assert {"workspace.create", "workspace.repository_added", "workspace.invitation_created", "workspace.member_joined"} <= set(actions)


# ---------------------------------------------------------------- notifications
def test_notifications_are_private_deduplicated_and_can_be_marked_read(ctx):
    from app.services import notification_service as ns
    ac, acsrf, repo_id, ws_id = setup_alice(ctx)
    bc, bcsrf, _ = invite_and_accept(ctx, ac, acsrf, ws_id, BOB)
    kinds = [n["kind"] for n in ac.get("/api/v1/notifications").json()["items"]]
    assert "workspace_member_joined" in kinds and ac.get("/api/v1/notifications/unread-count").json()["unread"] >= 1
    with ctx.db() as db:
        assert ns.notify(db, [1], kind="review_completed", title="t", dedup_key="same") == 1
        assert ns.notify(db, [1], kind="review_completed", title="t", dedup_key="same") == 0                              # the same event never notifies twice
        db.commit()
    page = ac.get("/api/v1/notifications?unread=true").json()
    nid = next(n["id"] for n in page["items"] if n["kind"] == "review_completed")
    assert bc.post(f"/api/v1/notifications/{nid}/read", headers=H(bcsrf)).status_code == 404                              # other users cannot touch it
    assert nid not in [n["id"] for n in bc.get("/api/v1/notifications").json()["items"]]
    assert ac.post(f"/api/v1/notifications/{nid}/read", headers=H(acsrf)).status_code == 204
    assert ac.post(f"/api/v1/notifications/{nid}/read", headers=H(acsrf)).status_code == 204                              # idempotent
    assert ac.post("/api/v1/notifications/read-all", headers=H(acsrf)).json()["marked"] >= 0
    assert ac.get("/api/v1/notifications/unread-count").json() == {"unread": 0}


def test_invitation_notifies_an_existing_user_and_unknown_links_are_not_stored(ctx):
    ac, acsrf, repo_id, ws_id = setup_alice(ctx)
    bc, bcsrf = login(ctx, BOB)                                                           # bob already has an account
    ac.post(f"/api/v1/workspaces/{ws_id}/invitations", json={"login": "bob"}, headers=H(acsrf))
    n = [x for x in bc.get("/api/v1/notifications").json()["items"] if x["kind"] == "workspace_invitation"]
    assert len(n) == 1 and n[0]["link"].startswith("/app/")
    from app.services import notification_service as ns
    with ctx.db() as db:
        ns.notify(db, [2], kind="x", title="t", link="https://evil.example/phish", dedup_key="evil"); db.commit()
    assert [x["link"] for x in bc.get("/api/v1/notifications").json()["items"] if x["kind"] == "x"] == [None]            # external links are dropped


# ---------------------------------------------------------------- export + deletion
def test_data_export_contains_account_data_without_secrets_and_is_owner_only(ctx):
    from app.models import BackgroundJob
    from app.workers.account_worker import handle_account_export
    ac, acsrf, repo_id, ws_id = setup_alice(ctx)
    r = ac.post("/api/v1/account/exports", headers=H(acsrf))
    assert r.status_code == 202 and r.json()["status"] == "pending"
    assert ac.post("/api/v1/account/exports", headers=H(acsrf)).json()["error"]["code"] == "export_pending"
    with ctx.db() as db:
        job = db.scalar(select(BackgroundJob).where(BackgroundJob.kind == "account_export"))
        handle_account_export(db, job)
    assert ac.get("/api/v1/account/exports").json()[0]["status"] == "ready"
    z = ac.get(f"/api/v1/account/exports/{r.json()['id']}/download")
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip" and z.headers["cache-control"] == "no-store"
    names = set(zipfile.ZipFile(io.BytesIO(z.content)).namelist())
    assert {"profile.json", "workspaces.json", "reviews.json", "findings.json", "notifications.json", "README.txt"} <= names
    blob = z.content + b"".join(zipfile.ZipFile(io.BytesIO(z.content)).read(n) for n in names)
    assert b"gho_plain_token" not in blob and b"access_token" not in blob and b"csrf" not in blob.lower() and b"token_hash" not in blob   # no credentials of any kind
    assert json.loads(zipfile.ZipFile(io.BytesIO(z.content)).read("profile.json"))["login"] == "alice"
    bc, bcsrf = login(ctx, BOB)
    assert bc.get(f"/api/v1/account/exports/{r.json()['id']}/download").status_code == 404                              # nobody else can download it
    assert ctx.client().get(f"/api/v1/account/exports/{r.json()['id']}/download").status_code == 401


def test_expired_exports_cannot_be_downloaded_and_are_cleaned_up(ctx):
    from datetime import timedelta
    from app.core.config import get_settings
    from app.db.base import utcnow
    from app.models import DataExport
    from app.services.retention import run_cleanup
    ac, acsrf, *_ = setup_alice(ctx)
    ex_id = ac.post("/api/v1/account/exports", headers=H(acsrf)).json()["id"]
    with ctx.db() as db:
        e = db.get(DataExport, ex_id); e.status, e.payload, e.expires_at = "ready", b"zip", utcnow() - timedelta(minutes=1); db.commit()
    assert ac.get(f"/api/v1/account/exports/{ex_id}/download").json()["error"]["code"] == "export_expired"
    assert run_cleanup(ctx.db, get_settings())["deleted"]["data_exports"] == 1


def test_account_deletion_requires_identity_proof_and_keeps_shared_workspaces(ctx):
    from app.models import AuditLog, OAuthIdentity, User, UserSession, Workspace, WorkspaceMember
    ac, acsrf, repo_id, ws_id = setup_alice(ctx)
    bc, bcsrf, _ = invite_and_accept(ctx, ac, acsrf, ws_id, BOB, "admin")
    solo = ac.post("/api/v1/workspaces", json={"name": "Solo"}, headers=H(acsrf)).json()
    assert ac.post("/api/v1/account/delete", json={"confirm_login": "someone-else"}, headers=H(acsrf)).json()["error"]["code"] == "confirmation_mismatch"
    with ctx.db() as db:
        s = db.scalar(select(UserSession).where(UserSession.user_id == 1)); s.created_at = s.created_at.replace(year=2020); db.commit()
    assert ac.post("/api/v1/account/delete", json={"confirm_login": "alice"}, headers=H(acsrf)).status_code == 403    # stale session: sign in again first
    ac, acsrf = login(ctx, {"id": 1, "login": "alice"})                                                              # fresh GitHub sign-in (as alice: the fake GitHub user was left as bob)
    r = ac.post("/api/v1/account/delete", json={"confirm_login": "alice"}, headers=H(acsrf))
    assert r.status_code == 204
    assert ac.get("/api/v1/auth/me").status_code == 401                                                              # signed out immediately
    with ctx.db() as db:
        assert db.scalar(select(User).where(User.login == "alice")) is None and db.scalar(select(OAuthIdentity).where(OAuthIdentity.user_id == 1)) is None
        assert db.get(Workspace, ws_id) is not None and db.get(Workspace, solo["id"]) is None                        # shared workspace survives, solo one is dissolved
        assert db.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws_id)).role == "owner"       # bob inherited ownership
        gone = db.scalar(select(AuditLog).where(AuditLog.action == "account.deleted"))
        assert gone.user_id is None and "alice" not in json.dumps(gone.meta)                                         # no personal data in the audit trail
    assert bc.get("/api/v1/github/repositories").json()["items"][0]["role"] == "owner"                               # bob still has the repository, now as owner
