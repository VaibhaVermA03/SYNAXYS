"""Edit / approve / publish / history for review comments, plus Phase 2: finding dismissal, queued-review cancellation and GitHub comment
deletion. Dismissal, deletion and publishing require repository ADMIN (owner) rights; cancelling needs admin rights or being the requester."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_github_client, rate_limit, settings_dep
from app.core.config import Settings
from app.core.exceptions import Forbidden
from app.db.session import get_db
from app.models import ReviewPostingAttempt, User
from app.repositories.access import get_review_for_user, repo_role
from app.schemas.reviews import (ApproveIn, ApproveOut, AttemptOut, CancelOut, CommentOut, CommentPatch, DeleteCommentOut, DismissIn, FindingStateOut,
                                 PublishOut)
from app.services import comment_delete, finding_service, publish_service, review_cancel
from app.services.github_service import GitHubClient

router = APIRouter(prefix="/reviews", tags=["review-actions"])
limit_publish = rate_limit("publish", 10)
limit_delete = rate_limit("comment_delete", 20)


def _finding_out(f) -> FindingStateOut:
    c = f.comment
    return FindingStateOut(id=f.id, status=f.status, dismissed_at=f.dismissed_at.isoformat() if f.dismissed_at else None, dismiss_reason=f.dismiss_reason, dismiss_note=f.dismiss_note,
                           comment=CommentOut(id=c.id, state=c.state, body=c.body, edited=c.edited, github_deleted_at=c.github_deleted_at.isoformat() if c.github_deleted_at else None) if c else None)


@router.patch("/{review_id}/comments/{comment_id}", response_model=CommentOut)
def edit_comment(review_id: int, comment_id: int, body: CommentPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    review, pr, _ = get_review_for_user(db, user, review_id, require_owner=True)
    c = publish_service.update_comment(db, user.id, review, pr, comment_id, body=body.body, state=body.state)
    return CommentOut(id=c.id, state=c.state, body=c.body, edited=c.edited, github_deleted_at=c.github_deleted_at.isoformat() if c.github_deleted_at else None)


@router.post("/{review_id}/findings/{finding_id}/dismiss", response_model=FindingStateOut)
def dismiss_finding(review_id: int, finding_id: int, body: DismissIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Dismiss ONE finding on its own: no comment needed, nothing deleted, who/when/why recorded. Idempotent."""
    review, pr, _ = get_review_for_user(db, user, review_id, require_owner=True)
    return _finding_out(finding_service.dismiss_finding(db, user.id, review, pr, finding_id, reason=body.reason, note=body.note))


@router.post("/{review_id}/findings/{finding_id}/restore", response_model=FindingStateOut)
def restore_finding(review_id: int, finding_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    review, pr, _ = get_review_for_user(db, user, review_id, require_owner=True)
    return _finding_out(finding_service.restore_finding(db, user.id, review, pr, finding_id))


@router.post("/{review_id}/cancel", response_model=CancelOut)
def cancel_review(review_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Cancel a review that is still waiting in the internal queue (not started, nothing on GitHub)."""
    review, pr, repo = get_review_for_user(db, user, review_id)
    if repo_role(db, user, repo.id) != "owner" and review.requested_by_id != user.id:
        raise Forbidden("Only a repository admin or the person who requested the review can cancel it")
    out = review_cancel.cancel_queued_review(db, user.id, review, pr)
    return CancelOut(status=review.status, cancelled_jobs=out["cancelled_jobs"])


@router.delete("/{review_id}/comments/{comment_id}/github", response_model=DeleteCommentOut, dependencies=[Depends(limit_delete)])
def delete_github_comment(review_id: int, comment_id: int, db: Session = Depends(get_db), user: User = Depends(current_user), s: Settings = Depends(settings_dep),
                          gh: GitHubClient = Depends(get_github_client)):
    """Delete a comment SYNAXYS published on GitHub. The internal record is kept (state 'deleted'); see services/comment_delete.py."""
    review, pr, repo = get_review_for_user(db, user, review_id, require_owner=True)
    return DeleteCommentOut(**comment_delete.delete_github_comment(db, s, gh, user.id, review, pr, repo, comment_id))


@router.post("/{review_id}/approve", response_model=ApproveOut)
def approve(review_id: int, body: ApproveIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    review, pr, _ = get_review_for_user(db, user, review_id, require_owner=True)
    return ApproveOut(approved=publish_service.approve_comments(db, user.id, review, pr, body.comment_ids))


@router.post("/{review_id}/publish", response_model=PublishOut, dependencies=[Depends(limit_publish)])
def publish(review_id: int, db: Session = Depends(get_db), user: User = Depends(current_user), s: Settings = Depends(settings_dep),
            gh: GitHubClient = Depends(get_github_client)):
    review, pr, repo = get_review_for_user(db, user, review_id, require_owner=True)
    return PublishOut(**publish_service.publish_review(db, s, gh, review, pr, repo, actor_id=user.id))


@router.get("/{review_id}/posting-attempts", response_model=list[AttemptOut])
def posting_attempts(review_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    review, _, _ = get_review_for_user(db, user, review_id)
    rows = db.execute(select(ReviewPostingAttempt, User.login).outerjoin(User, User.id == ReviewPostingAttempt.actor_user_id)
                      .where(ReviewPostingAttempt.review_id == review.id).order_by(ReviewPostingAttempt.id.desc()).limit(100)).all()
    return [AttemptOut(id=a.id, comment_id=a.comment_id, status=a.status, http_status=a.http_status, error=a.error, actor=login or ("auto-publish" if a.actor_user_id is None else None),
                       created_at=a.created_at.isoformat(), action=(a.response_meta or {}).get("action")) for a, login in rows]
