"""Independent finding dismissal (Phase 2).

Three separate state machines, never mixed:
  finding.status   open | dismissed | published      <- changed here (dismiss / restore)
  comment.state    draft | approved | published | failed | cancelled | deleted   <- GitHub comment lifecycle (publish_service, comment_delete)
  review.status    queued | processing | completed | failed | cancelled          <- review lifecycle
Dismissing never deletes data and never needs a comment: the original finding row (title, evidence, remediation...) stays; who/when/why are recorded.
A dismissed finding is excluded from counts and from publishing, and is remembered across later reviews of the same pull request."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequest, Conflict, NotFound, ValidationFailed
from app.core.security import contains_secret
from app.db.base import utcnow
from app.models import AuditLog, CodeReview, PullRequest, ReviewFinding
from app.services.review_workflow_logic import DISMISS_REASONS, build_dismissed_index


def _finding(db: Session, review: CodeReview, finding_id: int) -> ReviewFinding:
    f = db.get(ReviewFinding, finding_id)
    if f is None or f.review_id != review.id:  # a finding id from another review/repository is simply "not found"
        raise NotFound("Finding not found")
    return f


def dismiss_finding(db: Session, user_id: int, review: CodeReview, pr: PullRequest, finding_id: int, *, reason: str | None, note: str | None) -> ReviewFinding:
    if review.is_demo or pr.is_demo:
        raise BadRequest("Demo reviews are sample data and cannot be changed.", code="demo_readonly")
    f = _finding(db, review, finding_id)
    if f.status == "dismissed":
        return f  # idempotent: a double click records nothing twice
    if reason is not None and reason not in DISMISS_REASONS:
        raise ValidationFailed("Invalid reason", fields=[{"loc": ["reason"], "msg": "Unknown dismissal reason"}])
    text = (note or "").strip()
    if text and contains_secret(text):
        raise ValidationFailed("Invalid note", fields=[{"loc": ["note"], "msg": "The note appears to contain a secret or credential; remove it before saving"}])
    c = f.comment
    if c is not None and c.state == "publishing":
        raise Conflict("This finding's comment is being published right now. Try again in a moment.", code="publish_in_progress")
    before_comment = None
    if c is not None and c.state in ("draft", "approved", "failed"):  # a dismissed finding must never be published by accident
        before_comment, c.state = c.state, "cancelled"
    prev = f.status
    f.status, f.dismissed_by_id, f.dismissed_at, f.dismiss_reason, f.dismiss_note = "dismissed", user_id, utcnow(), reason, text or None
    db.add(AuditLog(user_id=user_id, action="finding.dismiss", target_type="finding", target_id=str(f.id),
                    meta={"review_id": review.id, "reason": reason, "previous_status": prev, "comment_state_before": before_comment}))
    db.commit()
    return f


def restore_finding(db: Session, user_id: int, review: CodeReview, pr: PullRequest, finding_id: int) -> ReviewFinding:
    if review.is_demo or pr.is_demo:
        raise BadRequest("Demo reviews are sample data and cannot be changed.", code="demo_readonly")
    f = _finding(db, review, finding_id)
    if f.status != "dismissed":
        return f  # idempotent
    c = f.comment
    f.status = "published" if (c is not None and c.state == "published") else "open"
    f.dismissed_by_id = f.dismissed_at = f.dismiss_reason = f.dismiss_note = None
    revived = False
    if c is not None and c.state == "cancelled":
        last = db.scalar(select(AuditLog).where(AuditLog.action == "finding.dismiss", AuditLog.target_type == "finding", AuditLog.target_id == str(f.id)).order_by(AuditLog.id.desc()).limit(1))
        if last is not None and (last.meta or {}).get("comment_state_before"):  # only undo a cancellation that the dismissal itself caused
            c.state, revived = "draft", True  # needs approval again
    db.add(AuditLog(user_id=user_id, action="finding.restore", target_type="finding", target_id=str(f.id), meta={"review_id": review.id, "comment_redrafted": revived}))
    db.commit()
    return f


def load_dismissed_index(db: Session, pull_request_id: int) -> dict:
    """Everything the team has dismissed on this pull request (all its reviews, including the one being re-run), as plain dicts so the
    result survives `review.findings.clear()`."""
    rows = db.execute(select(ReviewFinding.fingerprint, ReviewFinding.path, ReviewFinding.category, ReviewFinding.title, ReviewFinding.evidence,
                             ReviewFinding.dismissed_by_id, ReviewFinding.dismissed_at, ReviewFinding.dismiss_reason, ReviewFinding.dismiss_note)
                      .join(CodeReview, CodeReview.id == ReviewFinding.review_id)
                      .where(CodeReview.pull_request_id == pull_request_id, ReviewFinding.status == "dismissed").order_by(ReviewFinding.id)).all()
    return build_dismissed_index([dict(r._mapping) for r in rows])
