"""Dashboard aggregates computed only over repositories the caller can access."""
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.db.session import get_db
from app.db.base import utcnow
from app.models import CodeReview, PullRequest, Repository, ReviewComment, ReviewFinding, User
from app.repositories.access import accessible_repo_ids
from app.schemas.dashboard import DashboardOut, DayCount, RecentReview

router = APIRouter(tags=["dashboard"])
SEVERITIES = ["critical", "high", "medium", "low", "info"]


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db), user: User = Depends(current_user)):
    ids = accessible_repo_ids(db, user)
    repos = Repository.id.in_(ids)
    total = db.scalar(select(func.count()).select_from(Repository).where(repos)) or 0
    connected = db.scalar(select(func.count()).select_from(Repository).where(repos, Repository.is_enabled.is_(True))) or 0
    open_prs = db.scalar(select(func.count()).select_from(PullRequest).where(PullRequest.repository_id.in_(ids), PullRequest.state == "open")) or 0

    scoped_reviews = select(CodeReview.id).join(PullRequest, PullRequest.id == CodeReview.pull_request_id).where(PullRequest.repository_id.in_(ids))
    by_status = dict(db.execute(select(CodeReview.status, func.count()).where(CodeReview.id.in_(scoped_reviews)).group_by(CodeReview.status)).all())
    avg_ms = db.scalar(select(func.avg(CodeReview.duration_ms)).where(CodeReview.id.in_(scoped_reviews), CodeReview.status == "completed"))
    sev = dict(db.execute(select(ReviewFinding.severity, func.count()).where(ReviewFinding.review_id.in_(scoped_reviews), ReviewFinding.status != "dismissed")
                          .group_by(ReviewFinding.severity)).all())
    indexing = dict(db.execute(select(Repository.index_status, func.count()).where(repos).group_by(Repository.index_status)).all())

    rows = db.execute(
        select(CodeReview, PullRequest, Repository, select(func.count(ReviewFinding.id)).where(ReviewFinding.review_id == CodeReview.id).scalar_subquery())
        .join(PullRequest, PullRequest.id == CodeReview.pull_request_id).join(Repository, Repository.id == PullRequest.repository_id)
        .where(PullRequest.repository_id.in_(ids)).order_by(CodeReview.created_at.desc(), CodeReview.id.desc()).limit(10)).all()
    recent = [RecentReview(id=r.id, status=r.status, repository=repo.full_name, pr_number=pr.number, pr_title=pr.title, findings=n or 0,
                           created_at=r.created_at.isoformat(), duration_ms=r.duration_ms, is_demo=r.is_demo) for r, pr, repo, n in rows]
    since = (utcnow() - timedelta(days=13)).replace(hour=0, minute=0, second=0, microsecond=0)
    per_day: dict[str, int] = {}
    for (created,) in db.execute(select(CodeReview.created_at).where(CodeReview.id.in_(scoped_reviews), CodeReview.created_at >= since)).all():
        per_day[created.date().isoformat()] = per_day.get(created.date().isoformat(), 0) + 1
    days = [DayCount(date=(since + timedelta(days=i)).date().isoformat(), count=per_day.get((since + timedelta(days=i)).date().isoformat(), 0)) for i in range(14)]
    published = db.scalar(select(func.count()).select_from(ReviewComment).join(ReviewFinding, ReviewFinding.id == ReviewComment.finding_id)
                          .where(ReviewFinding.review_id.in_(scoped_reviews), ReviewComment.state == "published")) or 0
    has_demo = bool(db.scalar(select(func.count()).select_from(Repository).where(repos, Repository.is_demo.is_(True))))
    return DashboardOut(total_repositories=total, connected_repositories=connected, open_pull_requests=open_prs,
                        reviews_completed=by_status.get("completed", 0), reviews_by_status=by_status,
                        findings_by_severity={k: sev.get(k, 0) for k in SEVERITIES},
                        avg_review_duration_ms=int(avg_ms) if avg_ms is not None else None,
                        indexing_by_status=indexing, recent_reviews=recent, has_demo_data=has_demo,
                        reviews_by_day=days, published_comments=published, failed_reviews=by_status.get("failed", 0))
