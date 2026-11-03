"""Resource-level authorization. Every repository lookup goes through RepositoryAccess.

Missing OR unauthorized both raise NotFound so repository existence is not leaked.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import Forbidden, NotFound
from app.models import CodeReview, PullRequest, Repository, RepositoryAccess, User


def accessible_repo_ids(db: Session, user: User):
    return select(RepositoryAccess.repository_id).where(RepositoryAccess.user_id == user.id)


def get_repo_for_user(db: Session, user: User, repo_id: int, *, require_owner: bool = False) -> Repository:
    row = db.execute(
        select(Repository, RepositoryAccess.role)
        .join(RepositoryAccess, RepositoryAccess.repository_id == Repository.id)
        .where(Repository.id == repo_id, RepositoryAccess.user_id == user.id)
    ).first()
    if row is None:
        raise NotFound("Repository not found")
    repo, role = row
    if require_owner and role != "owner":
        raise Forbidden("Repository admin permission is required")
    return repo


def get_pr_for_user(db: Session, user: User, pr_id: int, *, require_owner: bool = False) -> tuple[PullRequest, Repository]:
    pr = db.get(PullRequest, pr_id)
    if pr is None:
        raise NotFound("Pull request not found")
    return pr, get_repo_for_user(db, user, pr.repository_id, require_owner=require_owner)  # NotFound if no access


def repo_role(db: Session, user: User, repo_id: int) -> str | None:
    return db.scalar(select(RepositoryAccess.role).where(RepositoryAccess.user_id == user.id, RepositoryAccess.repository_id == repo_id))


def get_review_for_user(db: Session, user: User, review_id: int, *, require_owner: bool = False) -> tuple[CodeReview, PullRequest, Repository]:
    review = db.get(CodeReview, review_id)
    if review is None:
        raise NotFound("Review not found")
    pr, repo = get_pr_for_user(db, user, review.pull_request_id, require_owner=require_owner)
    return review, pr, repo
