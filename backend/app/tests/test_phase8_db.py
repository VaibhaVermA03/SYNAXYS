"""Approval + publishing safety properties. NOT RUN in the build sandbox (needs deps)."""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.security import finding_fingerprint
from app.services.github_http import GitHubAPIError
from app.tests.conftest import login

FP = finding_fingerprint(1, 7, "app/users.py", 12, 12, "security", "SQL injection")


class FakeGH:
    def __init__(self, existing=None, review_error=None, bad_locations=(), single_error=None):
        self.existing, self.review_error, self.bad, self.single_error = existing or [], review_error, set(bad_locations), single_error
        self.reviews, self.singles = [], []
    user = {"id": 1, "login": "alice"}   # OAuth side, used by conftest.login()
    def exchange_code(self, code, verifier): return {"access_token": "gho_x", "scope": ""}
    def get_user(self, token): return self.user
    def list_user_installations(self, token): return []
    def list_user_installation_repos(self, token, iid): return []
    def installation_token(self, i): return "tok"
    def list_pull_request_review_comments(self, t, fn, n): return list(self.existing)
    def list_review_comments_of_review(self, t, fn, n, rid): return [{"id": 555, "body": c["body"]} for c in self.reviews[-1]["comments"]]
    def create_pull_request_review(self, t, fn, n, commit_id, body, comments):
        if self.review_error: raise self.review_error
        if any(c["line"] in self.bad for c in comments): raise GitHubAPIError(422)
        self.reviews.append({"commit_id": commit_id, "body": body, "comments": comments, "event": "COMMENT"}); return {"id": 77}
    def create_review_comment(self, t, fn, n, commit_id, c):
        if self.single_error: raise self.single_error
        if c["line"] in self.bad: raise GitHubAPIError(422)
        self.singles.append(c); return {"id": 900 + len(self.singles)}


@pytest.fixture()
def pub(ctx):
    """Alice (repo admin) + a completed review with one inline finding (draft comment) and one summary-only finding."""
    from app.models import (CodeReview, GitHubInstallation, PullRequest, Repository, RepositoryAccess, ReviewComment, ReviewConfiguration, ReviewFinding, User)
    with ctx.db() as db:
        u = User(github_id=1, login="alice"); db.add(u); db.flush()
        i = GitHubInstallation(installation_id=10, account_login="alice"); db.add(i); db.flush()
        r = Repository(installation_id=i.id, github_repo_id=100, full_name="alice/app", is_enabled=True); r.config = ReviewConfiguration(); db.add(r); db.flush()
        db.add(RepositoryAccess(user_id=u.id, repository_id=r.id, role="owner"))
        pr = PullRequest(repository_id=r.id, number=7, title="T", author_login="b", base_branch="main", head_branch="f", head_sha="a" * 40); db.add(pr); db.flush()
        rv = CodeReview(pull_request_id=pr.id, dedup_key="k", head_sha="a" * 40, status="completed", summary="AI summary"); db.add(rv); db.flush()
        f1 = ReviewFinding(review_id=rv.id, fingerprint=FP, category="security", severity="high", title="SQL injection", explanation="e", evidence="ev", path="app/users.py", start_line=12, end_line=12, inline_possible=True)
        f1.comment = ReviewComment(body="Draft body", state="draft")
        f2 = ReviewFinding(review_id=rv.id, fingerprint="f" * 32, category="bug", severity="low", title="Unplaced", explanation="e", evidence="ev", path="app/users.py", inline_possible=False)
        db.add_all([f1, f2]); db.commit()
        ctx.ids = SimpleNamespace(review=rv.id, pr=pr.id, repo=r.id, comment=f1.comment.id, finding=f1.id)
    ctx.gh = FakeGH()
    from app.api import deps
    ctx.app.dependency_overrides[deps.get_github_client] = lambda: ctx.gh
    return ctx


def as_admin(ctx):
    return login(ctx)   # github id 1 -> alice


def approve(c, csrf, ids):
    return c.post(f"/api/v1/reviews/{ids.review}/approve", json={}, headers={"X-CSRF-Token": csrf})


def comment_state(ctx):
    from app.models import ReviewComment
    with ctx.db() as db: return db.get(ReviewComment, ctx.ids.comment).state


def test_publish_requires_explicit_approval(pub):
    c, csrf = as_admin(pub); h = {"X-CSRF-Token": csrf}
    r = c.post(f"/api/v1/reviews/{pub.ids.review}/publish", headers=h)
    assert r.status_code == 400 and r.json()["error"]["code"] == "nothing_to_publish" and pub.gh.reviews == []
    assert approve(c, csrf, pub.ids).json() == {"approved": 1}
    assert c.get(f"/api/v1/reviews/{pub.ids.review}").json()["publishable"] is True


def test_publish_posts_one_comment_review_never_approving_with_marker_and_head_sha(pub):
    c, csrf = as_admin(pub); h = {"X-CSRF-Token": csrf}; approve(c, csrf, pub.ids)
    r = c.post(f"/api/v1/reviews/{pub.ids.review}/publish", headers=h)
    assert r.status_code == 200 and r.json() == {"posted": 1, "skipped_existing": 0, "failed": 0, "github_review_id": 77}
    sent = pub.gh.reviews[0]
    assert sent["event"] == "COMMENT" and sent["commit_id"] == "a" * 40 and sent["comments"][0]["side"] == "RIGHT" and sent["comments"][0]["line"] == 12
    assert f"synaxys:fp={FP}" in sent["comments"][0]["body"] and "Draft body" in sent["comments"][0]["body"]
    assert comment_state(pub) == "published"
    attempts = c.get(f"/api/v1/reviews/{pub.ids.review}/posting-attempts").json()
    assert attempts[0]["status"] == "success" and attempts[0]["actor"] == "alice"
    # second click must not post again
    assert c.post(f"/api/v1/reviews/{pub.ids.review}/publish", headers=h).json()["error"]["code"] == "nothing_to_publish" and len(pub.gh.reviews) == 1


def test_existing_marker_on_github_prevents_duplicate_even_if_db_state_was_lost(pub):
    pub.gh.existing = [{"id": 1, "body": f"old comment\n<!-- synaxys:fp={FP} -->"}]
    c, csrf = as_admin(pub); approve(c, csrf, pub.ids)
    r = c.post(f"/api/v1/reviews/{pub.ids.review}/publish", headers={"X-CSRF-Token": csrf})
    assert r.json()["skipped_existing"] == 1 and r.json()["posted"] == 0 and pub.gh.reviews == [] and comment_state(pub) == "published"


def test_stale_demo_and_disconnected_reviews_cannot_be_published(pub):
    from app.models import PullRequest, CodeReview, Repository
    c, csrf = as_admin(pub); h = {"X-CSRF-Token": csrf}; approve(c, csrf, pub.ids)
    with pub.db() as db: db.get(PullRequest, pub.ids.pr).head_sha = "b" * 40; db.commit()
    r = c.post(f"/api/v1/reviews/{pub.ids.review}/publish", headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "review_stale" and pub.gh.reviews == []
    assert c.get(f"/api/v1/reviews/{pub.ids.review}").json()["publish_blocker"] == "review_stale"
    with pub.db() as db:
        db.get(PullRequest, pub.ids.pr).head_sha = "a" * 40; db.get(Repository, pub.ids.repo).is_enabled = False; db.commit()
    assert c.post(f"/api/v1/reviews/{pub.ids.review}/publish", headers=h).json()["error"]["code"] == "repository_not_connected"
    with pub.db() as db: db.get(Repository, pub.ids.repo).is_enabled = True; db.get(CodeReview, pub.ids.review).is_demo = True; db.commit()
    assert c.post(f"/api/v1/reviews/{pub.ids.review}/publish", headers=h).json()["error"]["code"] == "demo_readonly"
    assert approve(c, csrf, pub.ids).json()["error"]["code"] == "demo_readonly" and pub.gh.reviews == []


def test_only_repo_admins_may_edit_approve_or_publish_and_csrf_required(pub):
    from app.models import RepositoryAccess
    c, csrf = as_admin(pub)
    assert c.post(f"/api/v1/reviews/{pub.ids.review}/approve", json={}).status_code == 403                    # CSRF
    with pub.db() as db:
        db.execute(RepositoryAccess.__table__.update().values(role="member")); db.commit()
    for path, m, body in ((f"/approve", "post", {}), (f"/publish", "post", None), (f"/comments/{pub.ids.comment}", "patch", {"body": "x"})):
        r = getattr(c, m)(f"/api/v1/reviews/{pub.ids.review}{path}", headers={"X-CSRF-Token": csrf}, **({"json": body} if body is not None else {}))
        assert r.status_code == 403, path
    eve, ecsrf = login(pub, {"id": 9, "login": "eve"})
    assert eve.post(f"/api/v1/reviews/{pub.ids.review}/approve", json={}, headers={"X-CSRF-Token": ecsrf}).status_code == 404
    assert pub.gh.reviews == []


def test_edit_resets_approval_validates_secrets_and_locks_after_publish(pub):
    c, csrf = as_admin(pub); h = {"X-CSRF-Token": csrf}; url = f"/api/v1/reviews/{pub.ids.review}/comments/{pub.ids.comment}"
    approve(c, csrf, pub.ids)
    r = c.patch(url, json={"body": "Edited by a human"}, headers=h).json()
    assert r["state"] == "draft" and r["edited"] is True                                                      # edit requires re-approval
    assert c.patch(url, json={"body": "   "}, headers=h).status_code == 422
    assert c.patch(url, json={"body": "token ghp_" + "a" * 36}, headers=h).status_code == 422
    assert c.patch(url, json={"state": "cancelled"}, headers=h).json()["state"] == "cancelled"
    assert approve(c, csrf, pub.ids).json() == {"approved": 0}                                                # cancelled comments are not approvable
    assert c.patch(url, json={"state": "draft"}, headers=h).json()["state"] == "draft"
    approve(c, csrf, pub.ids); c.post(f"/api/v1/reviews/{pub.ids.review}/publish", headers=h)
    assert c.patch(url, json={"body": "too late"}, headers=h).status_code == 409


def test_transient_github_failure_keeps_comment_approved_and_records_attempt(pub):
    pub.gh.review_error = GitHubAPIError(502)
    c, csrf = as_admin(pub); h = {"X-CSRF-Token": csrf}; approve(c, csrf, pub.ids)
    assert c.post(f"/api/v1/reviews/{pub.ids.review}/publish", headers=h).status_code == 502
    assert comment_state(pub) == "approved"
    a = c.get(f"/api/v1/reviews/{pub.ids.review}/posting-attempts").json()[0]
    assert a["status"] == "failed" and a["http_status"] == 502
    pub.gh.review_error = None
    assert c.post(f"/api/v1/reviews/{pub.ids.review}/publish", headers=h).json()["posted"] == 1                # retry works


def test_permission_denied_has_actionable_message(pub):
    pub.gh.review_error = GitHubAPIError(403)
    c, csrf = as_admin(pub); approve(c, csrf, pub.ids)
    r = c.post(f"/api/v1/reviews/{pub.ids.review}/publish", headers={"X-CSRF-Token": csrf})
    assert r.json()["error"]["code"] == "github_permission_denied" and "Pull requests" in r.json()["error"]["message"]


def test_invalid_line_422_isolates_bad_comment_and_posts_the_rest(pub):
    from app.models import ReviewComment, ReviewFinding
    with pub.db() as db:
        f = ReviewFinding(review_id=pub.ids.review, fingerprint="c" * 32, category="bug", severity="low", title="Second", explanation="e", evidence="ev",
                          path="app/users.py", start_line=40, end_line=40, inline_possible=True)
        f.comment = ReviewComment(body="second", state="draft"); db.add(f); db.commit()
    pub.gh.bad = {40}
    c, csrf = as_admin(pub); approve(c, csrf, pub.ids)
    r = c.post(f"/api/v1/reviews/{pub.ids.review}/publish", headers={"X-CSRF-Token": csrf}).json()
    assert r["posted"] == 1 and r["failed"] == 1 and pub.gh.reviews == [] and len(pub.gh.singles) == 1                # batch rejected, singles isolated
    with pub.db() as db:
        assert sorted(x.state for x in db.scalars(select(ReviewComment)).all()) == ["failed", "published"]


def test_concurrent_publish_lock_blocks_second_publisher(pub):
    from app.models import ReviewComment
    c, csrf = as_admin(pub); approve(c, csrf, pub.ids)
    with pub.db() as db: db.get(ReviewComment, pub.ids.comment).state = "publishing"; db.commit()               # a publish is in flight
    r = c.post(f"/api/v1/reviews/{pub.ids.review}/publish", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 400 and r.json()["error"]["code"] == "nothing_to_publish" and pub.gh.reviews == []


def test_config_endpoint_only_admins_and_auto_publish_policy_rules(pub):
    c, csrf = as_admin(pub); h = {"X-CSRF-Token": csrf}; url = f"/api/v1/github/repositories/{pub.ids.repo}/config"
    assert c.get(url).json()["auto_publish"] is False and c.get(url).json()["require_approval"] is True              # safe defaults
    assert c.patch(url, json={"auto_publish": True, "require_approval": True}, headers=h).status_code == 400
    r = c.patch(url, json={"auto_publish": True}, headers=h).json()
    assert r["auto_publish"] is True and r["require_approval"] is False
    assert c.patch(url, json={"require_approval": True}, headers=h).json()["auto_publish"] is False
    assert c.patch(url, json={"allowed_actions": ["deleted"]}, headers=h).status_code == 422
    assert c.patch(url, json={"max_files": 9999}, headers=h).status_code == 422


def test_auto_publish_job_respects_policy_at_execution_time(pub):
    from app.models import ReviewComment
    from app.services.publish_service import auto_publish_review
    from types import SimpleNamespace as NS
    s = NS(github_app_configured=True)
    with pub.db() as db:
        assert auto_publish_review(db, s, pub.gh, pub.ids.review) == "policy_disabled" and pub.gh.reviews == []   # not enabled -> nothing posted
    c, csrf = as_admin(pub); c.patch(f"/api/v1/github/repositories/{pub.ids.repo}/config", json={"auto_publish": True}, headers={"X-CSRF-Token": csrf})
    with pub.db() as db:
        assert auto_publish_review(db, s, pub.gh, pub.ids.review) == "published"
        assert db.get(ReviewComment, pub.ids.comment).state == "published"
    assert len(pub.gh.reviews) == 1 and pub.gh.reviews[0]["event"] == "COMMENT"
    attempts = c.get(f"/api/v1/reviews/{pub.ids.review}/posting-attempts").json()
    assert attempts[0]["actor"] == "auto-publish"
