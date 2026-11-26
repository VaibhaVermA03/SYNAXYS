"""Phase 2 (batch 14): finding dismissal, queued-review cancellation, GitHub comment deletion. NOT RUN in the authoring sandbox
(needs `pip install -r requirements-dev.txt`). Run: pytest -q app/tests/test_phase14_db.py"""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.tests.conftest import login

FP = "abcdef0123456789abcdef0123456789"
MARK = f"<!-- synaxys:fp={FP} -->"


def api_error(status):
    from app.services.github_http import GitHubAPIError  # lazy: ctx reloads app.* modules
    return GitHubAPIError(status)


class FakeGH:
    """GitHub double that only implements what comment deletion uses. comments: {id: review-comment dict}."""
    user = {"id": 1, "login": "alice"}

    def __init__(self):
        self.comments = {555: {"id": 555, "pull_request_url": "https://api.github.com/repos/alice/app/pulls/7", "body": f"body\n{MARK}", "user": {"login": "synaxys[bot]"}}}
        self.deleted, self.delete_error, self.keep_after_delete, self.calls = [], None, False, []

    def exchange_code(self, code, verifier): return {"access_token": "gho_x", "scope": ""}
    def get_user(self, token): return self.user
    def list_user_installations(self, token): return []
    def list_user_installation_repos(self, token, iid): return []
    def installation_token(self, i): return "tok"
    def list_pull_request_review_comments(self, t, fn, n): self.calls.append("list"); return list(self.comments.values())
    def get_review_comment(self, t, fn, cid):
        self.calls.append("get")
        if cid not in self.comments: raise api_error(404)
        return self.comments[cid]
    def delete_review_comment(self, t, fn, cid):
        self.calls.append("delete")
        if self.delete_error: raise self.delete_error
        self.deleted.append(cid)
        if not self.keep_after_delete: self.comments.pop(cid, None)


@pytest.fixture()
def wf(ctx):
    """alice (repo admin) + a completed review: f1 inline finding with a draft comment, f2 summary-only finding, f3 with a PUBLISHED comment (github id 555)."""
    from app.models import (CodeReview, GitHubInstallation, PullRequest, Repository, RepositoryAccess, ReviewComment, ReviewConfiguration, ReviewFinding, User)
    with ctx.db() as db:
        u = User(github_id=1, login="alice"); db.add(u); db.flush()
        i = GitHubInstallation(installation_id=10, account_login="alice"); db.add(i); db.flush()
        r = Repository(installation_id=i.id, github_repo_id=100, full_name="alice/app", is_enabled=True); r.config = ReviewConfiguration(); db.add(r); db.flush()
        db.add(RepositoryAccess(user_id=u.id, repository_id=r.id, role="owner"))
        pr = PullRequest(repository_id=r.id, number=7, title="T", author_login="b", base_branch="main", head_branch="f", head_sha="a" * 40,
                         html_url="https://github.com/alice/app/pull/7"); db.add(pr); db.flush()
        rv = CodeReview(pull_request_id=pr.id, dedup_key="k", head_sha="a" * 40, status="completed", summary="s", requested_by_id=u.id); db.add(rv); db.flush()
        f1 = ReviewFinding(review_id=rv.id, fingerprint="1" * 32, category="security", severity="high", title="SQL injection", explanation="e", evidence="q = f'{x}'", path="a.py", start_line=3, end_line=3, inline_possible=True)
        f1.comment = ReviewComment(body="draft", state="draft")
        f2 = ReviewFinding(review_id=rv.id, fingerprint="2" * 32, category="bug", severity="low", title="Unplaced", explanation="e", evidence="ev", path="a.py")
        f3 = ReviewFinding(review_id=rv.id, fingerprint=FP, category="bug", severity="medium", title="Published one", explanation="e", evidence="ev3", path="b.py", start_line=5, end_line=5, inline_possible=True, status="published")
        f3.comment = ReviewComment(body="pub", state="published", github_comment_id=555)
        db.add_all([f1, f2, f3]); db.commit()
        ctx.ids = SimpleNamespace(review=rv.id, pr=pr.id, repo=r.id, f1=f1.id, f2=f2.id, f3=f3.id, c1=f1.comment.id, c3=f3.comment.id)
    ctx.gh = FakeGH()
    from app.api import deps
    ctx.app.dependency_overrides[deps.get_github_client] = lambda: ctx.gh
    return ctx


def H(csrf): return {"X-CSRF-Token": csrf}
def U(wf, path): return f"/api/v1/reviews/{wf.ids.review}{path}"


# ---------------------------------------------------------------- Task 2: finding dismissal
def test_dismiss_needs_no_comment_keeps_data_and_records_who_when_why(wf):
    from app.models import AuditLog, ReviewFinding
    c, csrf = login(wf)
    r = c.post(U(wf, f"/findings/{wf.ids.f2}/dismiss"), json={"reason": "false_positive", "note": "test fixture"}, headers=H(csrf))   # f2 has NO comment
    assert r.status_code == 200 and r.json()["status"] == "dismissed" and r.json()["dismiss_reason"] == "false_positive" and r.json()["dismissed_at"]
    with wf.db() as db:
        f = db.get(ReviewFinding, wf.ids.f2)
        assert (f.title, f.evidence, f.explanation) == ("Unplaced", "ev", "e") and f.dismissed_by_id and f.dismiss_note == "test fixture"
    assert c.post(U(wf, f"/findings/{wf.ids.f2}/dismiss"), json={}, headers=H(csrf)).status_code == 200   # idempotent
    with wf.db() as db:
        assert len(db.scalars(select(AuditLog).where(AuditLog.action == "finding.dismiss")).all()) == 1


def test_dismiss_cancels_a_pending_comment_but_never_touches_a_published_one_and_restore_undoes_it(wf):
    c, csrf = login(wf)
    d = c.post(U(wf, f"/findings/{wf.ids.f1}/dismiss"), json={}, headers=H(csrf)).json()
    assert d["status"] == "dismissed" and d["comment"]["state"] == "cancelled"                         # cannot be published by accident
    d3 = c.post(U(wf, f"/findings/{wf.ids.f3}/dismiss"), json={"reason": "accepted_risk"}, headers=H(csrf)).json()
    assert d3["status"] == "dismissed" and d3["comment"]["state"] == "published"                       # GitHub comment state is independent
    r = c.get(U(wf, "")).json()
    assert r["dismissed_count"] == 2 and [f["id"] for f in r["findings_list"]] == [wf.ids.f2]            # active view hides dismissed
    allf = c.get(U(wf, "?include_dismissed=true")).json()["findings_list"]
    assert {f["id"] for f in allf} == {wf.ids.f1, wf.ids.f2, wf.ids.f3} and allf[-1]["status"] == "dismissed" and allf[-1]["dismissed_by"] == "alice"
    assert c.get(U(wf, "")).json()["by_severity"]["high"] == 0
    back = c.post(U(wf, f"/findings/{wf.ids.f1}/restore"), headers=H(csrf)).json()
    assert back["status"] == "open" and back["comment"]["state"] == "draft"
    assert c.post(U(wf, f"/findings/{wf.ids.f3}/restore"), headers=H(csrf)).json()["status"] == "published"


def test_dismiss_is_scoped_to_the_review_and_to_repository_admins(wf):
    from app.models import RepositoryAccess
    c, csrf = login(wf)
    assert c.post(U(wf, "/findings/999999/dismiss"), json={}, headers=H(csrf)).status_code == 404
    assert c.post(U(wf, f"/findings/{wf.ids.f2}/dismiss"), json={"reason": "nonsense"}, headers=H(csrf)).status_code == 422
    assert c.post(U(wf, f"/findings/{wf.ids.f2}/dismiss"), json={"note": "token ghp_" + "a1b2" * 9}, headers=H(csrf)).status_code == 422
    assert c.post(U(wf, f"/findings/{wf.ids.f2}/dismiss"), json={}).status_code == 403                  # CSRF
    with wf.db() as db:
        db.execute(RepositoryAccess.__table__.update().values(role="member")); db.commit()
    assert c.post(U(wf, f"/findings/{wf.ids.f2}/dismiss"), json={}, headers=H(csrf)).status_code == 403


def test_dismissed_findings_are_remembered_for_later_reviews_of_the_same_pull_request(wf):
    from app.services.finding_service import load_dismissed_index
    from app.services.review_workflow_logic import match_dismissed
    c, csrf = login(wf)
    c.post(U(wf, f"/findings/{wf.ids.f1}/dismiss"), json={"reason": "false_positive"}, headers=H(csrf))
    with wf.db() as db:
        idx = load_dismissed_index(db, wf.ids.pr)
    new = {"fingerprint": "9" * 32, "path": "a.py", "category": "security", "title": "SQL Injection", "evidence": "q = f'{x}'"}   # lines moved -> new fingerprint
    assert match_dismissed(new, idx)["dismiss_reason"] == "false_positive"
    assert match_dismissed({**new, "evidence": "something else"}, idx) is None


# ---------------------------------------------------------------- Task 3: cancel queued reviews
def _queued_review(wf, job_status="queued", review_status="queued", requested_by=None, key="q1"):
    from app.models import BackgroundJob, CodeReview
    with wf.db() as db:
        rv = CodeReview(pull_request_id=wf.ids.pr, dedup_key=key, head_sha="a" * 40, status=review_status, requested_by_id=requested_by); db.add(rv); db.flush()
        j = BackgroundJob(kind="review", payload={"review_id": rv.id}, dedup_key=f"review:{key}", status=job_status); db.add(j); db.commit()
        return rv.id, j.id


def test_cancel_queued_review_cancels_the_real_job_so_no_worker_can_take_it(wf):
    from app.models import AuditLog, BackgroundJob, CodeReview
    from app.services import job_queue
    rid, jid = _queued_review(wf)
    c, csrf = login(wf)
    detail = c.get(f"/api/v1/reviews/{rid}").json()
    assert detail["can_cancel"] is True
    r = c.post(f"/api/v1/reviews/{rid}/cancel", headers=H(csrf))
    assert r.status_code == 200 and r.json() == {"status": "cancelled", "cancelled_jobs": 1}
    with wf.db() as db:
        rv, j = db.get(CodeReview, rid), db.get(BackgroundJob, jid)
        assert rv.status == "cancelled" and rv.cancelled_by_id and rv.cancelled_at and rv.error == "Cancelled by user"
        assert j.status == "cancelled" and j.finished_at and "Cancelled" in j.last_error
        assert db.scalars(select(AuditLog).where(AuditLog.action == "review.cancel")).one().target_id == str(rid)
        assert job_queue.claim_next(db, "worker-1") is None                                             # a worker can never pick it up
    assert c.post(f"/api/v1/reviews/{rid}/cancel", headers=H(csrf)).json()["error"]["code"] == "already_cancelled"
    assert c.post(f"/api/v1/reviews/{rid}/retry", headers=H(csrf)).status_code == 202                  # a cancelled review can still be retried on purpose


def test_cancel_loses_the_race_against_a_worker_and_changes_nothing(wf):
    from app.models import BackgroundJob, CodeReview
    rid, jid = _queued_review(wf, job_status="processing")   # worker claimed the job; the review row still says 'queued'
    c, csrf = login(wf)
    r = c.post(f"/api/v1/reviews/{rid}/cancel", headers=H(csrf))
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_queued"
    with wf.db() as db:
        assert db.get(CodeReview, rid).status == "queued" and db.get(BackgroundJob, jid).status == "processing"


def test_only_queued_reviews_are_cancellable_and_only_by_admin_or_requester(wf):
    from app.models import RepositoryAccess, User
    c, csrf = login(wf)
    assert c.post(U(wf, "/cancel"), headers=H(csrf)).json()["error"]["code"] == "not_cancellable"     # completed review (maybe already on GitHub)
    r_run, _ = _queued_review(wf, review_status="processing", job_status="processing", key="run")
    assert c.post(f"/api/v1/reviews/{r_run}/cancel", headers=H(csrf)).json()["error"]["code"] == "already_running"
    with wf.db() as db:
        uid = db.scalar(select(User.id)); db.execute(RepositoryAccess.__table__.update().values(role="member")); db.commit()
    other, _ = _queued_review(wf, key="other")
    assert c.post(f"/api/v1/reviews/{other}/cancel", headers=H(csrf)).status_code == 403              # member who did not request it
    mine, _ = _queued_review(wf, requested_by=uid, key="mine")
    assert c.post(f"/api/v1/reviews/{mine}/cancel", headers=H(csrf)).status_code == 200               # the requester may cancel their own


# ---------------------------------------------------------------- Task 4: delete published GitHub comments
def delete(c, wf, csrf, cid=None):
    return c.delete(U(wf, f"/comments/{cid or wf.ids.c3}/github"), headers=H(csrf))


def test_delete_published_comment_verifies_deletes_confirms_and_keeps_the_record(wf):
    from app.models import AuditLog, ReviewComment, ReviewFinding, ReviewPostingAttempt
    c, csrf = login(wf)
    r = delete(c, wf, csrf)
    assert r.status_code == 200 and r.json() == {"outcome": "deleted", "state": "deleted"}
    assert wf.gh.deleted == [555] and wf.gh.calls == ["get", "delete", "get"]                          # fetched first, deleted, then re-checked
    with wf.db() as db:
        cm = db.get(ReviewComment, wf.ids.c3)
        assert cm.state == "deleted" and cm.github_deleted_at and cm.github_deleted_by_id and cm.body == "pub" and cm.github_comment_id == 555   # record kept
        assert db.get(ReviewFinding, wf.ids.f3).status == "open"                                         # the finding itself remains
        assert db.scalars(select(AuditLog).where(AuditLog.action == "comment.github_delete")).one().meta["github_comment_id"] == 555
        att = db.scalars(select(ReviewPostingAttempt).where(ReviewPostingAttempt.comment_id == wf.ids.c3)).one()
        assert att.status == "success" and att.response_meta["action"] == "delete"
    n = len(wf.gh.calls)
    assert delete(c, wf, csrf).json()["outcome"] == "already_deleted" and len(wf.gh.calls) == n          # idempotent, no GitHub traffic
    assert c.patch(U(wf, f"/comments/{wf.ids.c3}"), json={"body": "edit"}, headers=H(csrf)).status_code == 409   # deleted comments are locked
    assert c.get(U(wf, "/posting-attempts")).json()[0]["action"] == "delete"


def test_never_deletes_a_comment_that_is_not_ours_or_is_on_another_pull_request(wf):
    from app.models import ReviewComment
    c, csrf = login(wf)
    wf.gh.comments[555]["pull_request_url"] = "https://api.github.com/repos/alice/app/pulls/8"
    r = delete(c, wf, csrf)
    assert r.status_code == 409 and r.json()["error"]["code"] == "wrong_pull_request" and wf.gh.deleted == []
    wf.gh.comments[555].update(pull_request_url="https://api.github.com/repos/alice/app/pulls/7", body="a human comment, no marker")
    assert delete(c, wf, csrf).json()["error"]["code"] == "not_our_comment" and wf.gh.deleted == []
    with wf.db() as db:
        assert db.get(ReviewComment, wf.ids.c3).state == "published"


def test_permission_errors_and_unconfirmed_deletes_do_not_change_internal_state(wf):
    from app.models import ReviewComment, ReviewPostingAttempt
    c, csrf = login(wf)
    wf.gh.delete_error = api_error(403)
    r = delete(c, wf, csrf)
    assert r.status_code == 502 and r.json()["error"]["code"] == "github_permission_denied"
    wf.gh.delete_error, wf.gh.keep_after_delete = None, True                                             # GitHub says OK but the comment is still there
    assert delete(c, wf, csrf).json()["error"]["code"] == "delete_not_confirmed"
    with wf.db() as db:
        assert db.get(ReviewComment, wf.ids.c3).state == "published"
        assert {a.status for a in db.scalars(select(ReviewPostingAttempt)).all()} == {"failed"}


def test_comment_already_gone_on_github_is_reconciled_and_missing_ids_are_found_by_marker(wf):
    from app.models import ReviewComment
    c, csrf = login(wf)
    wf.gh.comments.clear()                                                                                # deleted on GitHub by someone else
    assert delete(c, wf, csrf).json() == {"outcome": "already_deleted", "state": "deleted"}
    with wf.db() as db:
        assert db.get(ReviewComment, wf.ids.c3).state == "deleted"


def test_missing_github_comment_id_is_resolved_via_the_fingerprint_marker(wf):
    from app.models import ReviewComment
    with wf.db() as db:
        db.get(ReviewComment, wf.ids.c3).github_comment_id = None; db.commit()
    c, csrf = login(wf)
    assert delete(c, wf, csrf).json()["outcome"] == "deleted" and wf.gh.deleted == [555] and "list" in wf.gh.calls


def test_delete_requires_a_published_comment_and_repository_admin(wf):
    from app.models import RepositoryAccess
    c, csrf = login(wf)
    assert delete(c, wf, csrf, wf.ids.c1).json()["error"]["code"] == "not_published"
    assert delete(c, wf, csrf, 999999).status_code == 404
    assert c.delete(U(wf, f"/comments/{wf.ids.c3}/github")).status_code == 403                          # CSRF
    with wf.db() as db:
        db.execute(RepositoryAccess.__table__.update().values(role="member")); db.commit()
    assert delete(c, wf, csrf).status_code == 403 and wf.gh.deleted == []
