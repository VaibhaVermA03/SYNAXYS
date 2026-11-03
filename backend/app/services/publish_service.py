"""Approval and authorized publishing of review comments to GitHub.

Safety properties (each covered by tests):
* only comments a repo admin approved (or an owner-enabled auto-publish policy) are ever posted;
* only findings with a verified inline diff location have comments; event is always COMMENT;
* stale reviews (PR head moved) are refused; demo data is never published;
* per-comment 'publishing' lock + fingerprint markers on GitHub => no duplicate comments, even
  after crashes/retries; every outcome is recorded in review_posting_attempts and audit logs.
"""
from datetime import timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import BadRequest, Conflict, NotConfigured, NotFound, UpstreamError, ValidationFailed
from app.core.security import contains_secret
from app.db.base import utcnow
from app.models import (AuditLog, CodeReview, GitHubInstallation, PullRequest, Repository, ReviewComment, ReviewFinding, ReviewPostingAttempt)
from app.services.github_http import GitHubAPIError
from app.services.publish_logic import BLOCKERS, can_transition, existing_markers, inline_payload, plan, publish_blocker, with_marker

LOCK_TTL = timedelta(minutes=5)


def blocker_error(code: str):
    status, msg = BLOCKERS[code]
    return (NotConfigured if status == 503 else Conflict if status == 409 else BadRequest)(msg, code=code)


def review_comments(db: Session, review: CodeReview) -> list[ReviewComment]:
    return list(db.scalars(select(ReviewComment).join(ReviewFinding, ReviewFinding.id == ReviewComment.finding_id)
                           .where(ReviewFinding.review_id == review.id).order_by(ReviewComment.id)).all())


def _require_actionable(review: CodeReview, pr: PullRequest) -> None:
    if review.is_demo or pr.is_demo:
        raise blocker_error("demo_readonly")
    if review.status != "completed":
        raise blocker_error("review_not_completed")


def approve_comments(db: Session, user_id: int | None, review: CodeReview, pr: PullRequest, comment_ids: list[int] | None) -> int:
    _require_actionable(review, pr)
    comments = review_comments(db, review)
    by_id = {c.id: c for c in comments}
    if comment_ids is not None and any(i not in by_id for i in comment_ids):
        raise NotFound("Comment not found")
    targets = [c for c in comments if c.state == "draft" and (comment_ids is None or c.id in comment_ids)]
    for c in targets:
        c.state, c.approved_by_id = "approved", user_id
    if targets:
        review.approved_by_id, review.approved_at = user_id, utcnow()
        db.add(AuditLog(user_id=user_id, action="review.approve" if user_id else "review.auto_approve", target_type="review", target_id=str(review.id),
                        meta={"comments": [c.id for c in targets]}))
    db.commit()
    return len(targets)


def update_comment(db: Session, user_id: int, review: CodeReview, pr: PullRequest, comment_id: int, *, body: str | None, state: str | None) -> ReviewComment:
    _require_actionable(review, pr)
    c = next((x for x in review_comments(db, review) if x.id == comment_id), None)
    if c is None:
        raise NotFound("Comment not found")
    if c.state in ("published", "publishing"):
        raise Conflict("This comment is already published or being published and can no longer be changed.", code="comment_locked")
    if body is not None:
        text = body.strip()
        if not text:
            raise ValidationFailed("Invalid comment", fields=[{"loc": ["body"], "msg": "Comment cannot be empty"}])
        if contains_secret(text):
            raise ValidationFailed("Invalid comment", fields=[{"loc": ["body"], "msg": "Comment appears to contain a secret or credential; remove it before saving"}])
        c.body, c.edited = text, True
        if c.state in ("approved", "failed"):
            c.state = "draft"  # an edit always needs re-approval
    if state is not None and state != c.state:
        if not can_transition(c.state, state):
            raise Conflict(f"Cannot change a {c.state} comment to {state}.", code="invalid_transition")
        c.state = state
    db.add(AuditLog(user_id=user_id, action="comment.update", target_type="comment", target_id=str(c.id), meta={"state": c.state, "edited": body is not None}))
    db.commit()
    return c


def _attempt(db, review, comment_id, actor, status, http_status=None, meta=None, error=None):
    db.add(ReviewPostingAttempt(review_id=review.id, comment_id=comment_id, actor_user_id=actor, status=status, http_status=http_status,
                                response_meta=meta, error=(error or None) and str(error)[:500]))


def _release(db: Session, ids: list[int]) -> None:
    db.execute(update(ReviewComment).where(ReviewComment.id.in_(ids), ReviewComment.state == "publishing").values(state="approved"))
    db.commit()


def _mark_published(db, c: ReviewComment, f: ReviewFinding, github_id=None):
    c.state, c.github_comment_id, f.status = "published", github_id, "published"


def publish_review(db: Session, s: Settings, gh, review: CodeReview, pr: PullRequest, repo: Repository, *, actor_id: int | None) -> dict:
    code = publish_blocker(review_status=review.status, is_demo=review.is_demo or pr.is_demo, repo_enabled=repo.is_enabled, pr_state=pr.state,
                           pr_head=pr.head_sha, review_head=review.head_sha, app_configured=s.github_app_configured)
    if code:
        raise blocker_error(code)
    now = utcnow()
    stale = now - LOCK_TTL
    candidates = [c.id for c in review_comments(db, review)
                  if c.state == "approved" or (c.state == "publishing" and _aware_lt(c.updated_at, stale))]
    if not candidates:
        raise BadRequest("There are no approved comments to publish.", code="nothing_to_publish")
    res = db.execute(update(ReviewComment).where(ReviewComment.id.in_(candidates), or_(ReviewComment.state == "approved",
                     and_(ReviewComment.state == "publishing", ReviewComment.updated_at < stale))).values(state="publishing", updated_at=now))
    db.commit()
    if res.rowcount != len(candidates):  # another publisher took some: back out and report
        db.execute(update(ReviewComment).where(ReviewComment.id.in_(candidates), ReviewComment.state == "publishing", ReviewComment.updated_at == now).values(state="approved"))
        db.commit()
        raise Conflict("Another publish is already in progress for this review.", code="publish_in_progress")

    comments = {c.id: c for c in review_comments(db, review) if c.id in candidates}
    findings = {c.id: db.get(ReviewFinding, c.finding_id) for c in comments.values()}
    items = [{"fingerprint": findings[cid].fingerprint, "cid": cid} for cid in comments]
    result = {"posted": 0, "skipped_existing": 0, "failed": 0, "github_review_id": None}
    try:
        inst = db.get(GitHubInstallation, repo.installation_id)
        token = gh.installation_token(inst.installation_id)
        existing = existing_markers(gh.list_pull_request_review_comments(token, repo.full_name, pr.number))
        to_post, dups = plan(items, existing)
        for it in dups:
            c = comments[it["cid"]]
            _mark_published(db, c, findings[c.id])
            _attempt(db, review, c.id, actor_id, "skipped", error="Already on GitHub (fingerprint marker found)")
            result["skipped_existing"] += 1
        db.commit()
        if to_post:
            _post(db, gh, token, repo, pr, review, comments, findings, to_post, actor_id, result)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        _release(db, list(comments))
        _attempt(db, review, None, actor_id, "failed", getattr(exc, "status", None), error=getattr(exc, "message", type(exc).__name__))
        db.commit()
        if isinstance(exc, GitHubAPIError) and exc.status in (401, 403, 404):
            raise UpstreamError("GitHub rejected the request. Check the GitHub App has 'Pull requests: Read & write' permission on this repository.",
                                code="github_permission_denied") from exc
        raise
    db.add(AuditLog(user_id=actor_id, action="review.publish", target_type="review", target_id=str(review.id), meta=result))
    db.commit()
    return result


def _aware_lt(dt, bound) -> bool:
    from app.services.auth_service import aware
    return aware(dt) < bound


def _post(db, gh, token, repo, pr, review, comments, findings, to_post, actor_id, result) -> None:
    payloads = {}
    for it in to_post:
        c, f = comments[it["cid"]], findings[it["cid"]]
        payloads[c.id] = inline_payload(f.path, f.start_line, f.end_line, with_marker(c.body, f.fingerprint))
    body = (review.summary or "SYNAXYS AI-assisted review.") + f"\n\n<!-- synaxys:review={review.id} -->"
    try:
        resp = gh.create_pull_request_review(token, repo.full_name, pr.number, review.head_sha, body, list(payloads.values()))
        gh_ids = {}
        try:  # best effort: map GitHub comment ids back for traceability
            for gc in gh.list_review_comments_of_review(token, repo.full_name, pr.number, resp["id"]):
                for fp in existing_markers([gc]):
                    gh_ids[fp] = gc.get("id")
        except Exception:  # noqa: BLE001
            pass
        result["github_review_id"] = resp.get("id")
        for it in to_post:
            c, f = comments[it["cid"]], findings[it["cid"]]
            _mark_published(db, c, f, gh_ids.get(f.fingerprint))
            _attempt(db, review, c.id, actor_id, "success", 200, {"github_review_id": resp.get("id")})
            result["posted"] += 1
        db.commit()
        return
    except GitHubAPIError as exc:
        if exc.status != 422:
            raise
    # GitHub rejects the whole review if ANY comment location is invalid: isolate the bad ones.
    for it in to_post:
        c, f = comments[it["cid"]], findings[it["cid"]]
        try:
            resp = gh.create_review_comment(token, repo.full_name, pr.number, review.head_sha, payloads[c.id])
            _mark_published(db, c, f, resp.get("id"))
            _attempt(db, review, c.id, actor_id, "success", 201, {"mode": "single"})
            result["posted"] += 1
        except GitHubAPIError as exc:
            if exc.status != 422:
                raise
            c.state = "failed"
            _attempt(db, review, c.id, actor_id, "failed", 422, error="GitHub rejected this comment's diff location")
            result["failed"] += 1
        db.commit()  # persist each outcome immediately; a later crash cannot cause a re-post (markers) or lose state


def auto_publish_review(db: Session, s: Settings, gh, review_id: int) -> str:
    """Owner-enabled auto-publish. Re-checks the policy at execution time."""
    review = db.get(CodeReview, review_id)
    if review is None:
        return "missing"
    pr = db.get(PullRequest, review.pull_request_id)
    repo = db.get(Repository, pr.repository_id)
    cfg = repo.config
    if not (cfg and cfg.auto_publish):
        return "policy_disabled"
    code = publish_blocker(review_status=review.status, is_demo=review.is_demo or pr.is_demo, repo_enabled=repo.is_enabled, pr_state=pr.state,
                           pr_head=pr.head_sha, review_head=review.head_sha, app_configured=s.github_app_configured)
    if code:
        return code  # nothing to retry (stale, closed, ...)
    approve_comments(db, None, review, pr, None)
    try:
        publish_review(db, s, gh, review, pr, repo, actor_id=None)
    except BadRequest as e:
        if e.code == "nothing_to_publish":
            return "nothing_to_publish"
        raise
    return "published"
