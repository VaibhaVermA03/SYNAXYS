"""Queue + webhook + worker behaviour on SQLite. NOT RUN in the build sandbox (needs deps)."""
import hashlib, hmac, json
from datetime import timedelta
import pytest
from sqlalchemy import select

from app.tests.conftest import login  # noqa: F401  (ensures env fixtures import)

SECRET = "whsec"


def _post(c, event, payload, delivery="d1", secret=SECRET, sig=None):
    body = json.dumps(payload).encode()
    sig = sig or "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return c.post("/api/v1/webhooks/github", content=body, headers={"X-GitHub-Event": event, "X-GitHub-Delivery": delivery,
                                                                     "X-Hub-Signature-256": sig, "Content-Type": "application/json"})


def _pr(number=1, sha="a" * 40, action="opened", state="open", repo_id=100):
    return {"action": action, "number": number, "repository": {"id": repo_id}, "installation": {"id": 10},
            "pull_request": {"title": "T", "state": state, "merged": False, "user": {"login": "bob"},
                             "base": {"ref": "main"}, "head": {"ref": "f", "sha": sha}}}


@pytest.fixture()
def repo_env(ctx):
    from app.models import GitHubInstallation, Repository, ReviewConfiguration
    with ctx.db() as db:
        inst = GitHubInstallation(installation_id=10, account_login="alice"); db.add(inst); db.flush()
        r = Repository(installation_id=inst.id, github_repo_id=100, full_name="alice/app", default_branch="main", is_enabled=True)
        r.config = ReviewConfiguration(); db.add(r); db.commit(); ctx.repo_id = r.id
    return ctx


def _jobs(ctx, kind=None):
    from app.models import BackgroundJob
    with ctx.db() as db:
        q = select(BackgroundJob); q = q.where(BackgroundJob.kind == kind) if kind else q
        return db.scalars(q).all()


def test_signature_checks(repo_env):
    c = repo_env.client()
    assert _post(c, "pull_request", _pr(), sig="sha256=" + "0" * 64).status_code == 401
    assert c.post("/api/v1/webhooks/github", content=b"{}", headers={"X-GitHub-Event": "ping", "X-GitHub-Delivery": "x"}).status_code == 401
    assert _post(c, "ping", {}).json() == {"status": "pong"}
    assert _post(c, "pull_request", _pr(), secret="wrong").status_code == 401
    assert _jobs(repo_env) == []


def test_pr_opened_queues_one_review_and_duplicate_delivery_is_noop(repo_env):
    c = repo_env.client()
    r1 = _post(c, "pull_request", _pr()); assert r1.status_code == 202 and r1.json()["status"] == "queued"
    r2 = _post(c, "pull_request", _pr()); assert r2.status_code == 200 and r2.json()["status"] == "duplicate"
    assert len(_jobs(repo_env, "review")) == 1
    r3 = _post(c, "pull_request", _pr(), delivery="d2")                      # new delivery, same commit
    assert r3.json()["status"] == "ignored" and len(_jobs(repo_env, "review")) == 1


def test_closed_unknown_repo_disabled_repo_do_not_enqueue(repo_env):
    c = repo_env.client()
    assert _post(c, "pull_request", _pr(action="closed", state="closed"), "c1").json()["status"] == "updated"
    assert _post(c, "pull_request", _pr(repo_id=999), "c2").json()["status"] == "ignored"
    from app.models import Repository
    with repo_env.db() as db:
        db.get(Repository, repo_env.repo_id).is_enabled = False; db.commit()
    assert _post(c, "pull_request", _pr(number=2), "c3").json()["status"] == "updated"
    assert _jobs(repo_env, "review") == []


def test_synchronize_cancels_superseded_queued_review(repo_env):
    c = repo_env.client()
    _post(c, "pull_request", _pr(sha="a" * 40), "s1")
    _post(c, "pull_request", _pr(sha="b" * 40, action="synchronize"), "s2")
    st = sorted(j.status for j in _jobs(repo_env, "review"))
    assert st == ["cancelled", "queued"]


def test_invalid_payload_400_and_failed_delivery_can_be_redelivered(repo_env):
    c = repo_env.client()
    bad = _pr(); bad["pull_request"]["head"]["sha"] = "zzz"
    assert _post(c, "pull_request", bad, "r1").status_code == 400
    assert _post(c, "pull_request", _pr(), "r1").status_code == 202          # same GUID after failure is processed
    assert _post(c, "pull_request", _pr(), "r1").status_code == 200          # now a true duplicate


def test_push_default_branch_enqueues_index_once(repo_env):
    c = repo_env.client()
    p = {"ref": "refs/heads/main", "after": "c" * 40, "repository": {"id": 100, "default_branch": "main"}}
    assert _post(c, "push", p, "p1").json()["status"] == "queued"
    assert _post(c, "push", p, "p2").json()["status"] == "ignored"
    assert _post(c, "push", {**p, "ref": "refs/heads/dev"}, "p3").json()["status"] == "ignored"
    assert len(_jobs(repo_env, "index")) == 1


def test_installation_deleted_disables_repos_and_queues_cleanup(repo_env):
    c = repo_env.client()
    _post(c, "installation", {"action": "deleted", "installation": {"id": 10, "account": {"login": "alice"}}}, "i1")
    from app.models import Repository
    with repo_env.db() as db:
        assert db.get(Repository, repo_env.repo_id).is_enabled is False
    assert len(_jobs(repo_env, "index_delete")) == 1


# ---- queue semantics ----------------------------------------------------------------
def test_enqueue_dedup_claim_exclusive_retry_and_final_failure(ctx):
    from app.services import job_queue as q
    with ctx.db() as db:
        j, created = q.enqueue(db, "review", {"x": 1}, "k1", max_attempts=2); db.commit()
        assert created and q.enqueue(db, "review", {}, "k1")[1] is False
        a = q.claim_next(db, "w1"); assert a and a.attempts == 1
        assert q.claim_next(db, "w2") is None                                   # exclusive
        assert q.complete(db, a.id, "w2") is False                              # fenced: wrong worker
        assert q.fail(db, a.id, "w1", RuntimeError("t ghp_" + "a" * 36), rand=lambda: 0.0) == "queued"
        from app.models import BackgroundJob
        row = db.get(BackgroundJob, a.id); assert "ghp_" not in row.last_error and row.run_after > row.created_at
        assert q.claim_next(db, "w1") is None                                   # backoff not elapsed
        b = q.claim_next(db, "w1", now=row.run_after + timedelta(seconds=1)); assert b.attempts == 2
        assert q.fail(db, b.id, "w1", "again") == "failed"                      # max attempts reached
        assert q.requeue(db, b.id) and db.get(BackgroundJob, b.id).attempts == 0


def test_stale_lock_recovery(ctx):
    from app.services import job_queue as q
    from app.db.base import utcnow
    with ctx.db() as db:
        q.enqueue(db, "review", {}, "k", timeout_seconds=60); db.commit()
        j = q.claim_next(db, "dead-worker")
        assert q.recover_stale(db, now=utcnow()) == []
        assert q.recover_stale(db, now=utcnow() + timedelta(seconds=120)) == [(j.id, "queued")]
        assert q.complete(db, j.id, "dead-worker") is False                     # zombie rejected


def test_worker_retry_and_unknown_handler_and_review_marked_failed(ctx):
    from app.models import CodeReview, GitHubInstallation, PullRequest, Repository
    from app.services import job_queue as q
    from app.workers.runner import Worker
    from types import SimpleNamespace
    with ctx.db() as db:
        i = GitHubInstallation(installation_id=1, account_login="a"); db.add(i); db.flush()
        r = Repository(installation_id=i.id, github_repo_id=1, full_name="a/b"); db.add(r); db.flush()
        pr = PullRequest(repository_id=r.id, number=1, title="t", author_login="x", base_branch="m", head_branch="f", head_sha="a" * 40); db.add(pr); db.flush()
        rv = CodeReview(pull_request_id=pr.id, dedup_key="d", head_sha="a" * 40, status="queued"); db.add(rv); db.flush()
        q.enqueue(db, "review", {"review_id": rv.id}, "rk", max_attempts=1); db.commit(); rid = rv.id
    s = SimpleNamespace(worker_heartbeat_path="/tmp/x", worker_concurrency=1)
    w = Worker(ctx.db, {}, s, "w")                                              # no handlers registered
    assert w.run_once() is True
    with ctx.db() as db:
        assert db.get(CodeReview, rid).status == "failed" and "No handler" in db.get(CodeReview, rid).error
