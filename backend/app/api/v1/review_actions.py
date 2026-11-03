"""Edit / approve / publish / history for review comments. All require repository ADMIN (owner) rights."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_github_client, rate_limit, settings_dep
from app.core.config import Settings
from app.db.session import get_db
from app.models import ReviewPostingAttempt, User
from app.repositories.access import get_review_for_user
from app.schemas.reviews import ApproveIn, ApproveOut, AttemptOut, CommentOut, CommentPatch, PublishOut
from app.services import publish_service
from app.services.github_service import GitHubClient

router = APIRouter(prefix="/reviews", tags=["review-actions"])
limit_publish = rate_limit("publish", 10)


@router.patch("/{review_id}/comments/{comment_id}", response_model=CommentOut)
def edit_comment(review_id: int, comment_id: int, body: CommentPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    review, pr, _ = get_review_for_user(db, user, review_id, require_owner=True)
    c = publish_service.update_comment(db, user.id, review, pr, comment_id, body=body.body, state=body.state)
    return CommentOut(id=c.id, state=c.state, body=c.body, edited=c.edited)


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
                       created_at=a.created_at.isoformat()) for a, login in rows]
