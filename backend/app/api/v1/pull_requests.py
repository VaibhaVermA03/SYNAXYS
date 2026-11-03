"""Pull-request feed, detail, diff, and manual review requests (all scoped via RepositoryAccess)."""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_github_client, rate_limit, settings_dep
from app.core.config import Settings
from app.core.exceptions import BadRequest, NotConfigured
from app.db.session import get_db
from app.models import AuditLog, CodeReview, GitHubInstallation, PullRequest, Repository, ReviewFinding, User
from app.repositories.access import accessible_repo_ids, get_pr_for_user
from app.schemas.pull_requests import DiffOut, PullRequestDetail, PullRequestOut, PullRequestPage, ReviewBrief
from app.services import job_queue
from app.services.diff_service import build_file_diff, count_patch_changes
from app.services.github_service import GitHubClient

router = APIRouter(prefix="/pull-requests", tags=["pull-requests"])
limit_review = rate_limit("manual_review", 20)
SEVERITIES = ["critical", "high", "medium", "low", "info"]
SORTS = {"updated": PullRequest.github_updated_at, "created": PullRequest.created_at, "number": PullRequest.number}


def pr_state(pr: PullRequest) -> str:
    return "merged" if pr.merged else pr.state


def _iso(dt):
    return dt.isoformat() if dt else ""


def review_briefs(db: Session, reviews: list[CodeReview]) -> dict[int, ReviewBrief]:
    ids = [r.id for r in reviews]
    sev: dict[int, dict[str, int]] = {i: {s: 0 for s in SEVERITIES} for i in ids}
    if ids:
        for rid, s, n in db.execute(select(ReviewFinding.review_id, ReviewFinding.severity, func.count()).where(
                ReviewFinding.review_id.in_(ids), ReviewFinding.status != "dismissed").group_by(ReviewFinding.review_id, ReviewFinding.severity)).all():
            sev[rid][s] = n
    return {r.id: ReviewBrief(id=r.id, status=r.status, trigger=r.trigger, findings=sum(sev[r.id].values()), by_severity=sev[r.id],
                              created_at=_iso(r.created_at), finished_at=_iso(r.finished_at) or None, duration_ms=r.duration_ms,
                              error=r.error, is_demo=r.is_demo, head_sha=r.head_sha) for r in reviews}


def _pr_out(pr: PullRequest, repo: Repository, brief: ReviewBrief | None) -> dict:
    return dict(id=pr.id, repository_id=repo.id, repository=repo.full_name, number=pr.number, title=pr.title, author=pr.author_login,
                state=pr_state(pr), base_branch=pr.base_branch, head_branch=pr.head_branch, html_url=pr.html_url,
                updated_at=_iso(pr.github_updated_at or pr.updated_at), is_demo=pr.is_demo, review=brief)


@router.get("", response_model=PullRequestPage)
def list_pull_requests(q: str | None = None, repository_id: int | None = None, state: str | None = Query(None, pattern="^(open|closed|merged)$"),
                       review_status: str | None = Query(None, pattern="^(none|queued|processing|completed|failed|cancelled)$"),
                       sort: str = Query("updated", pattern="^(updated|created|number)$"), order: str = Query("desc", pattern="^(asc|desc)$"),
                       page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                       db: Session = Depends(get_db), user: User = Depends(current_user)):
    ids = accessible_repo_ids(db, user)
    latest = select(func.max(CodeReview.id)).where(CodeReview.pull_request_id == PullRequest.id).correlate(PullRequest).scalar_subquery()
    base = (select(PullRequest, Repository, CodeReview).join(Repository, Repository.id == PullRequest.repository_id)
            .outerjoin(CodeReview, CodeReview.id == latest).where(PullRequest.repository_id.in_(ids)))
    if repository_id:
        base = base.where(PullRequest.repository_id == repository_id)
    if q:
        like = f"%{q.replace('%', '').replace('_', '')}%"
        base = base.where(PullRequest.title.ilike(like) | PullRequest.author_login.ilike(like) | Repository.full_name.ilike(like))
    if state == "merged":
        base = base.where(PullRequest.merged.is_(True))
    elif state == "open":
        base = base.where(PullRequest.state == "open")
    elif state == "closed":
        base = base.where(PullRequest.state == "closed", PullRequest.merged.is_(False))
    if review_status == "none":
        base = base.where(CodeReview.id.is_(None))
    elif review_status:
        base = base.where(CodeReview.status == review_status)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    col = SORTS[sort]
    base = base.order_by((col.asc() if order == "asc" else col.desc()), PullRequest.id.desc()).limit(page_size).offset((page - 1) * page_size)
    rows = db.execute(base).all()
    briefs = review_briefs(db, [r for _, _, r in rows if r is not None])
    items = [PullRequestOut(**_pr_out(pr, repo, briefs.get(rv.id) if rv else None)) for pr, repo, rv in rows]
    return PullRequestPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/{pull_request_id}", response_model=PullRequestDetail)
def pull_request_detail(pull_request_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    pr, repo = get_pr_for_user(db, user, pull_request_id)
    reviews = db.scalars(select(CodeReview).where(CodeReview.pull_request_id == pr.id).order_by(CodeReview.id.desc()).limit(20)).all()
    briefs = review_briefs(db, list(reviews))
    ordered = [briefs[r.id] for r in reviews]
    return PullRequestDetail(**_pr_out(pr, repo, ordered[0] if ordered else None), head_sha=pr.head_sha, repo_enabled=repo.is_enabled,
                             can_request_review=repo.is_enabled and not pr.is_demo and pr.state == "open", reviews=ordered)


@router.get("/{pull_request_id}/diff", response_model=DiffOut)
def pull_request_diff(pull_request_id: int, db: Session = Depends(get_db), user: User = Depends(current_user),
                      s: Settings = Depends(settings_dep), gh: GitHubClient = Depends(get_github_client)):
    pr, repo = get_pr_for_user(db, user, pull_request_id)
    cfg = repo.config
    max_files = cfg.max_files if cfg else s.review_max_files
    max_bytes = cfg.max_patch_bytes if cfg else s.review_max_patch_bytes
    if pr.is_demo:  # fixture data stored locally; never presented as live GitHub content
        raw = [{"filename": p, "status": "modified", "patch": patch, **dict(zip(("additions", "deletions"), count_patch_changes(patch)))}
               for p, patch in (pr.demo_patches or {}).items()]
    else:
        if not s.github_app_configured:
            raise NotConfigured("GitHub App is not configured; cannot fetch diffs. Set GITHUB_APP_ID and a private key.", code="github_app_not_configured")
        inst = db.get(GitHubInstallation, repo.installation_id)
        raw = gh.list_pull_request_files(gh.installation_token(inst.installation_id), repo.full_name, pr.number)
    files = [build_file_diff(f, max_bytes) for f in raw[:max_files]]
    return DiffOut(files=files, omitted_files=max(0, len(raw) - max_files), head_sha=pr.head_sha, is_demo=pr.is_demo)


@router.post("/{pull_request_id}/review", response_model=ReviewBrief, status_code=202, dependencies=[Depends(limit_review)])
def request_review(pull_request_id: int, db: Session = Depends(get_db), user: User = Depends(current_user), s: Settings = Depends(settings_dep)):
    pr, repo = get_pr_for_user(db, user, pull_request_id)
    if pr.is_demo:
        raise BadRequest("Demo pull requests are read-only sample data and cannot be reviewed.", code="demo_readonly")
    if not repo.is_enabled:
        raise BadRequest("Connect this repository before requesting a review.", code="repository_not_connected")
    if pr.state != "open":
        raise BadRequest("Only open pull requests can be reviewed.", code="pr_not_open")
    active = db.scalar(select(CodeReview).where(CodeReview.pull_request_id == pr.id, CodeReview.head_sha == pr.head_sha,
                                                 CodeReview.status.in_(["queued", "processing"])))
    if active is None:  # double-clicks return the review already in flight
        active = CodeReview(pull_request_id=pr.id, head_sha=pr.head_sha, trigger="manual", requested_by_id=user.id, status="queued",
                            dedup_key=f"pr:{repo.id}:{pr.number}:sha:{pr.head_sha}:manual:{uuid.uuid4().hex[:8]}")
        db.add(active)
        db.flush()
        job_queue.enqueue(db, "review", {"review_id": active.id}, f"review:{active.dedup_key}", max_attempts=s.job_max_attempts,
                          timeout_seconds=s.job_default_timeout_seconds)
        db.add(AuditLog(user_id=user.id, action="review.requested", target_type="review", target_id=str(active.id)))
        db.commit()
    return review_briefs(db, [active])[active.id]
