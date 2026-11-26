"""Delete a comment that SYNAXYS published on GitHub (Phase 2).

Safety rules (each is a separate step, in this order):
 1. only repository admins (checked by the API), never demo data, only comments in state 'published'
 2. the comment id is fetched FROM GITHUB first and must (a) belong to this repository and pull request, (b) carry our hidden marker for
    THIS finding, (c) be authored by our GitHub App bot when GITHUB_APP_SLUG is set. Otherwise nothing is deleted.
 3. the installation token of THIS repository's installation is used (so GitHub enforces the app's own permissions)
 4. after DELETE we GET the comment again: only a 404 counts as success. A 204 alone is never trusted.
 5. only then the internal row is updated: state='deleted' (+ who/when). The row is never removed; the finding stays.
 6. every outcome is written to review_posting_attempts (action=delete) and, on success, to the audit log.
GitHub 404 on lookup = it is already gone: the internal state is brought in line and reported as 'already_deleted'.
The review SUMMARY body of the GitHub review is not a review comment and is not touched."""
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import BadRequest, Conflict, NotFound, RateLimited, UpstreamError
from app.db.base import utcnow
from app.models import AuditLog, CodeReview, GitHubInstallation, PullRequest, Repository, ReviewComment, ReviewFinding, ReviewPostingAttempt
from app.services.github_http import GitHubAPIError
from app.services.publish_service import blocker_error, review_comments
from app.services.review_workflow_logic import DELETE_BLOCKERS, marker_fingerprints, verify_comment_ownership


def _attempt(db: Session, review: CodeReview, comment_id: int, actor: int, status: str, http_status: int | None, meta: dict, error: str | None = None) -> None:
    db.add(ReviewPostingAttempt(review_id=review.id, comment_id=comment_id, actor_user_id=actor, status=status, http_status=http_status,
                                response_meta={"action": "delete", **meta}, error=(error or None) and str(error)[:500]))


def _find_on_github(gh, token: str, repo: Repository, pr: PullRequest, fingerprint: str) -> int | None:
    """Fallback when the GitHub comment id was not stored at publish time: locate our comment by its marker."""
    for gc in gh.list_pull_request_review_comments(token, repo.full_name, pr.number):
        if fingerprint in marker_fingerprints(gc.get("body")) and gc.get("id") is not None:
            return int(gc["id"])
    return None


def _gone(gh, token: str, repo: Repository, gh_id: int) -> bool:
    """True only if GitHub answers 404 for this comment."""
    try:
        gh.get_review_comment(token, repo.full_name, gh_id)
    except GitHubAPIError as exc:
        if exc.status == 404:
            return True
        raise
    return False


def delete_github_comment(db: Session, s: Settings, gh, user_id: int, review: CodeReview, pr: PullRequest, repo: Repository, comment_id: int) -> dict:
    if review.is_demo or pr.is_demo:
        raise BadRequest(DELETE_BLOCKERS["demo_readonly"], code="demo_readonly")
    c: ReviewComment | None = next((x for x in review_comments(db, review) if x.id == comment_id), None)
    if c is None:
        raise NotFound("Comment not found")
    if c.state == "deleted":
        return {"outcome": "already_deleted", "state": "deleted"}  # idempotent
    if c.state != "published":
        raise Conflict(DELETE_BLOCKERS["not_published"], code="not_published")
    if not s.github_app_configured:
        raise blocker_error("github_app_not_configured")
    f: ReviewFinding = db.get(ReviewFinding, c.finding_id)
    inst = db.get(GitHubInstallation, repo.installation_id)
    if inst is None:
        raise Conflict("The GitHub installation for this repository is missing. Reconnect the repository.", code="installation_missing")
    meta: dict = {}
    try:
        token = gh.installation_token(inst.installation_id)
        gh_id = c.github_comment_id or _find_on_github(gh, token, repo, pr, f.fingerprint)
        meta["github_comment_id"] = gh_id
        outcome = "deleted"
        if gh_id is None:
            outcome = "already_deleted"  # no comment with our marker exists on the pull request any more
        else:
            try:
                gc = gh.get_review_comment(token, repo.full_name, gh_id)
            except GitHubAPIError as exc:
                if exc.status != 404:
                    raise
                outcome = "already_deleted"
            else:
                reason = verify_comment_ownership(gc, full_name=repo.full_name, number=pr.number, fingerprint=f.fingerprint, app_slug=s.github_app_slug)
                if reason:
                    _attempt(db, review, c.id, user_id, "skipped", None, meta, DELETE_BLOCKERS[reason])
                    db.commit()
                    raise Conflict(DELETE_BLOCKERS[reason], code=reason)
                try:
                    gh.delete_review_comment(token, repo.full_name, gh_id)
                except GitHubAPIError as exc:
                    if exc.status != 404:
                        raise
                if not _gone(gh, token, repo, gh_id):
                    _attempt(db, review, c.id, user_id, "failed", None, meta, DELETE_BLOCKERS["still_exists"])
                    db.commit()
                    raise UpstreamError(DELETE_BLOCKERS["still_exists"], code="delete_not_confirmed")
    except (Conflict, UpstreamError, RateLimited) as exc:
        if getattr(exc, "code", "") in ("delete_not_confirmed", *DELETE_BLOCKERS):
            raise  # already recorded above
        db.rollback()
        status = getattr(exc, "status", None)
        _attempt(db, review, c.id, user_id, "failed", status, meta, getattr(exc, "message", type(exc).__name__))
        db.commit()
        if isinstance(exc, GitHubAPIError) and status in (401, 403):
            raise UpstreamError("GitHub refused to delete the comment. The GitHub App needs 'Pull requests: Read & write' on this repository and must be installed on it.",
                                code="github_permission_denied") from exc
        raise
    now = utcnow()
    res = db.execute(update(ReviewComment).where(ReviewComment.id == c.id, ReviewComment.state == "published")
                     .values(state="deleted", github_deleted_at=now, github_deleted_by_id=user_id, github_comment_id=meta.get("github_comment_id") or c.github_comment_id))
    if res.rowcount == 1:
        if f.status == "published":
            f.status = "open"  # the finding itself remains; it is simply no longer on GitHub
        _attempt(db, review, c.id, user_id, "success", 204 if outcome == "deleted" else 404, {**meta, "outcome": outcome})
        db.add(AuditLog(user_id=user_id, action="comment.github_delete", target_type="comment", target_id=str(c.id),
                        meta={"review_id": review.id, "pull_request": pr.number, "github_comment_id": meta.get("github_comment_id"), "outcome": outcome}))
    db.commit()  # rowcount 0 = a concurrent request already did it: same final state, nothing duplicated
    return {"outcome": outcome, "state": "deleted"}
