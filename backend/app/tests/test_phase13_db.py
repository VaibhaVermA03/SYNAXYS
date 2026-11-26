"""Phase 1 hardening: admin job screen + retention cleanup + rate-limit wiring. NOT RUN in the authoring sandbox (needs
`pip install -r requirements-dev.txt`). Run with: pytest -q app/tests/test_phase13_db.py"""
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.tests.conftest import login


@pytest.fixture()
def actx(monkeypatch, request):
    monkeypatch.setenv("ADMIN_GITHUB_IDS", "1")  # the fake GitHub user 'alice' has id 1
    return request.getfixturevalue("ctx")


def _job(ctx, **kw):
    from app.db.base import utcnow
    from app.models import BackgroundJob
    base = dict(kind="review", status="failed", attempts=4, max_attempts=4, last_error="boom", finished_at=utcnow(),
                payload={"review_id": 9999, "repository_id": 5, "token": "ghp_SHOULD_NEVER_SHOW", "diff": "def x(): pass"})
    with ctx.db() as db:
        j = BackgroundJob(**{**base, **kw})
        db.add(j); db.commit()
        return j.id


def test_non_admin_cannot_reach_admin_api_and_is_not_flagged(ctx):
    c, csrf = login(ctx)  # ADMIN_GITHUB_IDS is empty
    assert c.get("/api/v1/auth/me").json()["is_admin"] is False
    jid = _job(ctx)
    assert c.get("/api/v1/admin/jobs").status_code == 404
    assert c.get("/api/v1/admin/jobs/summary").status_code == 404
    assert c.get(f"/api/v1/admin/jobs/{jid}").status_code == 404
    assert c.post(f"/api/v1/admin/jobs/{jid}/retry", headers={"X-CSRF-Token": csrf}).status_code == 404


def test_anonymous_is_rejected(ctx):
    assert ctx.client().get("/api/v1/admin/jobs").status_code == 401


def test_admin_lists_failed_jobs_with_safe_fields_only(actx):
    c, _ = login(actx)
    assert c.get("/api/v1/auth/me").json()["is_admin"] is True
    jid = _job(actx)
    _job(actx, status="succeeded", last_error=None)
    body = c.get("/api/v1/admin/jobs").json()
    assert [i["id"] for i in body["items"]] == [jid] and body["total"] == 1 and body["items"][0]["can_retry"] is True
    detail = c.get(f"/api/v1/admin/jobs/{jid}").json()
    assert detail["payload"] == {"review_id": 9999, "repository_id": 5}  # allow-list only
    assert "ghp_SHOULD_NEVER_SHOW" not in c.get(f"/api/v1/admin/jobs/{jid}").text and "def x" not in c.get(f"/api/v1/admin/jobs/{jid}").text
    assert len(c.get("/api/v1/admin/jobs?status=&page_size=1").json()["items"]) == 1 and c.get("/api/v1/admin/jobs?status=bogus").status_code == 400
    s = c.get("/api/v1/admin/jobs/summary").json()
    assert s["by_status"]["failed"] == 1 and s["by_status"]["succeeded"] == 1 and s["failed_by_kind"] == {"review": 1} and s["total"] == 2


def test_retry_is_csrf_protected_idempotent_and_audited(actx):
    from app.models import AuditLog, BackgroundJob
    c, csrf = login(actx)
    jid = _job(actx, kind="publish", payload={"review_id": 1})
    assert c.post(f"/api/v1/admin/jobs/{jid}/retry").status_code == 403  # no CSRF header
    r = c.post(f"/api/v1/admin/jobs/{jid}/retry", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 202 and r.json()["status"] == "queued" and r.json()["attempts"] == 0 and r.json()["error"] is None
    again = c.post(f"/api/v1/admin/jobs/{jid}/retry", headers={"X-CSRF-Token": csrf})
    assert again.status_code == 409 and again.json()["error"]["code"] == "not_retryable"  # double click = exactly one requeue
    with actx.db() as db:
        assert db.get(BackgroundJob, jid).status == "queued"
        a = db.scalars(select(AuditLog).where(AuditLog.action == "admin.job_retry")).all()
        assert len(a) == 1 and a[0].target_id == str(jid) and a[0].meta["previous_error"] == "boom"


def test_only_failed_jobs_can_be_retried(actx):
    c, csrf = login(actx)
    for st in ("queued", "processing", "succeeded", "cancelled"):
        jid = _job(actx, status=st)
        assert c.post(f"/api/v1/admin/jobs/{jid}/retry", headers={"X-CSRF-Token": csrf}).status_code == 409
    assert c.post("/api/v1/admin/jobs/424242/retry", headers={"X-CSRF-Token": csrf}).status_code == 404


def test_cleanup_deletes_only_expired_data_and_is_idempotent(actx):
    from app.core.config import get_settings
    from app.db.base import utcnow
    from app.models import AuditLog, BackgroundJob, User, UserSession, WebhookDelivery
    from app.services.retention import run_cleanup
    login(actx)
    now = utcnow()
    with actx.db() as db:
        uid = db.scalar(select(User.id))
        db.add_all([UserSession(token_hash="expired", csrf_secret="c", user_id=uid, expires_at=now - timedelta(days=30)),
                    UserSession(token_hash="revoked-old", csrf_secret="c", user_id=uid, expires_at=now + timedelta(days=1), revoked_at=now - timedelta(days=30)),
                    WebhookDelivery(delivery_id="old", event="push", received_at=now - timedelta(days=90)),
                    WebhookDelivery(delivery_id="new", event="push", received_at=now),
                    AuditLog(action="review.publish", created_at=now - timedelta(days=400)),
                    AuditLog(action="auth.login", created_at=now - timedelta(days=400)),   # security record: kept (< 730 days)
                    BackgroundJob(kind="review", status="succeeded", finished_at=now - timedelta(days=30), dedup_key="a"),
                    BackgroundJob(kind="review", status="queued", dedup_key="b", created_at=now - timedelta(days=500)),   # never deleted
                    BackgroundJob(kind="review", status="failed", finished_at=now - timedelta(days=30), dedup_key="c")])  # < 60 days: kept
        db.commit()
    s = get_settings()
    dry = run_cleanup(actx.db, s, dry_run=True)
    assert dry["deleted"]["sessions"] == 2 and dry["deleted"]["webhook_deliveries"] == 1
    with actx.db() as db:
        assert db.scalar(select(func.count()).select_from(WebhookDelivery)) == 2  # dry run deleted nothing
    r1 = run_cleanup(actx.db, s)
    assert r1["deleted"]["sessions"] == 2 and r1["deleted"]["webhook_deliveries"] == 1 and r1["deleted"]["jobs_done"] == 1
    assert r1["deleted"]["audit_general"] == 1 and r1["deleted"]["jobs_failed"] == 0 and not r1["errors"]
    with actx.db() as db:
        assert {x for (x,) in db.execute(select(UserSession.token_hash))} and db.scalar(select(func.count()).select_from(UserSession).where(UserSession.revoked_at.is_(None), UserSession.expires_at > now)) == 1
        assert {j.dedup_key for j in db.scalars(select(BackgroundJob))} == {"b", "c"}
        assert {a.action for a in db.scalars(select(AuditLog))} >= {"auth.login", "system.cleanup"} and "review.publish" not in {a.action for a in db.scalars(select(AuditLog))}
    r2 = run_cleanup(actx.db, s)
    assert sum(r2["deleted"].values()) == 0  # idempotent


def test_user_rate_limit_is_enforced_per_authenticated_user(monkeypatch, request):
    monkeypatch.setenv("USER_RATE_LIMIT_PER_MINUTE", "5")
    ctx = request.getfixturevalue("ctx")
    c, _ = login(ctx)
    codes = [c.get("/api/v1/dashboard").status_code for _ in range(8)]
    assert codes.count(429) >= 1 and codes[0] != 429
    assert ctx.client().get("/api/v1/health").status_code == 200  # health is exempt


def test_security_headers_present_on_api_responses(ctx):
    r = ctx.client().get("/api/v1/health")
    assert r.headers["x-content-type-options"] == "nosniff" and "frame-ancestors 'none'" in r.headers["content-security-policy"] and r.headers.get("x-request-id")
