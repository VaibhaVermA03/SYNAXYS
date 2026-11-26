"""Indexing control + status for a repository (admin to start, any member to view)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, rate_limit, settings_dep
from app.api.v1.code_search import REASONS
from app.core.config import Settings
from app.core.exceptions import BadRequest, Conflict, NotConfigured, NotFound, UpstreamError
from app.db.session import get_db
from app.models import AuditLog, BranchIndexState, GitHubInstallation, IndexedFile, IndexingBatch, IndexingJob, User
from app.repositories.access import get_repo_for_user
from app.schemas.search import BranchStateOut, GitHubBranchesOut, IndexBranchIn, IndexJobOut, IndexStatusOut
from app.api.deps import get_github_client
from app.services import indexing_service, job_queue
from app.services.github_http import GitHubAPIError
from app.services.github_service import GitHubClient
from app.services.vector_service import indexing_available

router = APIRouter(prefix="/repositories", tags=["repositories"])
limit_index = rate_limit("index", 6)


def _iso(d):
    return d.isoformat() if d else None


def _job_out(db: Session, j: IndexingJob) -> IndexJobOut:
    counts = dict(db.execute(select(IndexingBatch.status, func.count()).where(IndexingBatch.job_id == j.id).group_by(IndexingBatch.status)).all())
    return IndexJobOut(id=j.id, status=j.status, commit=j.commit_sha, files_total=j.files_total, files_indexed=j.files_indexed, chunks_upserted=j.chunks_upserted,
                       error=j.error, created_at=_iso(j.created_at), started_at=_iso(j.started_at), finished_at=_iso(j.finished_at), branch=j.branch,
                       batches={k: counts.get(k, 0) for k in ("pending", "done", "failed")} if counts else None, plan=j.plan_summary)


def _branch_out(st: BranchIndexState, default: str) -> BranchStateOut:
    return BranchStateOut(branch=st.branch, is_default=st.branch == default, status=st.status, last_indexed_commit=st.last_indexed_commit, last_indexed_at=_iso(st.last_indexed_at),
                          error=st.error, files_indexed=st.files_indexed, files_eligible=st.files_eligible, files_deferred=st.files_deferred, failed_batches=st.failed_batches,
                          tree_incomplete=st.tree_incomplete)


def _status(db: Session, repo, s: Settings, branch: str | None = None) -> IndexStatusOut:
    ok, reason = indexing_available(s)
    branch = branch or repo.default_branch
    latest = db.scalar(select(IndexingJob).where(IndexingJob.repository_id == repo.id, IndexingJob.branch == branch).order_by(IndexingJob.id.desc()).limit(1))
    n = db.scalar(select(func.count()).select_from(IndexedFile).where(IndexedFile.repository_id == repo.id, IndexedFile.branch == branch)) or 0
    states = db.scalars(select(BranchIndexState).where(BranchIndexState.repository_id == repo.id).order_by(BranchIndexState.branch)).all()
    st = next((x for x in states if x.branch == branch), None)
    return IndexStatusOut(branch=branch, branches=sorted((_branch_out(x, repo.default_branch) for x in states), key=lambda b: (not b.is_default, b.branch)),
                          status=(st.status if st else repo.index_status if branch == repo.default_branch else "not_indexed"), available=ok, unavailable_reason=reason,
                          backend="memory (demo)" if s.vector_backend == "memory" else "pinecone",
                          last_indexed_at=_iso(st.last_indexed_at if st else repo.last_indexed_at if branch == repo.default_branch else None),
                          last_indexed_commit=st.last_indexed_commit if st else repo.last_indexed_commit if branch == repo.default_branch else None,
                          error=st.error if st else repo.index_error if branch == repo.default_branch else None, indexed_files=n, job=_job_out(db, latest) if latest else None)


@router.get("/{repository_id}/index-status", response_model=IndexStatusOut)
def index_status(repository_id: int, branch: str | None = Query(None, max_length=200, pattern=r"^[\w./\-]+$"), db: Session = Depends(get_db), user: User = Depends(current_user),
                 s: Settings = Depends(settings_dep)):
    return _status(db, get_repo_for_user(db, user, repository_id), s, branch)


@router.get("/{repository_id}/github-branches", response_model=GitHubBranchesOut)
def github_branches(repository_id: int, db: Session = Depends(get_db), user: User = Depends(current_user), s: Settings = Depends(settings_dep),
                    gh: GitHubClient = Depends(get_github_client)):
    """Live branch names from GitHub (installation token), so an admin can choose which extra branch to index."""
    repo = get_repo_for_user(db, user, repository_id, require_owner=True)
    if repo.is_demo or not repo.is_enabled or not s.github_app_configured:
        raise BadRequest("Connect this repository (and configure the GitHub App) to list its branches.", code="branches_unavailable")
    inst = db.get(GitHubInstallation, repo.installation_id)
    try:
        names = gh.list_branches(gh.installation_token(inst.installation_id), repo.full_name)
    except GitHubAPIError as exc:
        raise UpstreamError("GitHub could not list the branches of this repository.", code="github_branches_failed") from exc
    indexed = db.scalars(select(BranchIndexState.branch).where(BranchIndexState.repository_id == repo.id)).all()
    return GitHubBranchesOut(default_branch=repo.default_branch, branches=names, indexed=sorted(indexed), max_extra_branches=s.index_max_branches)


def _check_branch(db: Session, s: Settings, gh: GitHubClient, repo, branch: str) -> None:
    """A non-default branch must exist on GitHub and fit the per-repository branch limit (bounds Pinecone usage)."""
    if branch == repo.default_branch:
        return
    known = db.scalar(select(BranchIndexState.id).where(BranchIndexState.repository_id == repo.id, BranchIndexState.branch == branch))
    if known is None:
        extra = db.scalar(select(func.count()).select_from(BranchIndexState).where(BranchIndexState.repository_id == repo.id, BranchIndexState.branch != repo.default_branch)) or 0
        if extra >= s.index_max_branches:
            raise BadRequest(f"At most {s.index_max_branches} extra branches can be indexed per repository. Remove one first.", code="too_many_branches")
    try:
        gh.get_branch_head(gh.installation_token(db.get(GitHubInstallation, repo.installation_id).installation_id), repo.full_name, branch)
    except GitHubAPIError as exc:
        if exc.status in (400, 404):
            raise NotFound(f"Branch '{branch}' was not found on GitHub (deleted, renamed or no access).") from exc
        raise UpstreamError("GitHub could not be reached to verify the branch.", code="github_unavailable") from exc


def _queue_job(db: Session, repo, branch: str, user_id: int, key_prefix: str, job: IndexingJob) -> None:
    db.flush()
    job_queue.enqueue(db, "index", {"repository_id": repo.id, "branch": branch, "indexing_job_id": job.id}, f"{key_prefix}:{job.id}", timeout_seconds=1800)


def _admin_repo(db: Session, user: User, repository_id: int, s: Settings):
    repo = get_repo_for_user(db, user, repository_id, require_owner=True)
    if repo.is_demo:
        raise BadRequest("Demo repositories are sample data and cannot be indexed.", code="demo_readonly")
    if not repo.is_enabled:
        raise BadRequest("Connect this repository before indexing.", code="repository_not_connected")
    if repo.config is not None and not repo.config.index_enabled:
        raise BadRequest("Indexing is disabled in this repository's review configuration.", code="index_disabled")
    ok, reason = indexing_available(s)
    if not ok:
        raise NotConfigured(REASONS[reason], code=reason)  # never queue work that is certain to fail
    return repo


@router.post("/{repository_id}/index", response_model=IndexStatusOut, status_code=202, dependencies=[Depends(limit_index)])
def start_index(repository_id: int, body: IndexBranchIn | None = None, db: Session = Depends(get_db), user: User = Depends(current_user), s: Settings = Depends(settings_dep),
                gh: GitHubClient = Depends(get_github_client)):
    """Index (or incrementally refresh) one branch; no body = the default branch. Only changed files are processed."""
    repo = _admin_repo(db, user, repository_id, s)
    branch = (body.branch if body and body.branch else None) or repo.default_branch
    active = db.scalar(select(IndexingJob).where(IndexingJob.repository_id == repo.id, IndexingJob.branch == branch, IndexingJob.status.in_(["queued", "indexing"])))
    if active is None:  # double-clicks reuse the running job
        _check_branch(db, s, gh, repo, branch)
        active = IndexingJob(repository_id=repo.id, branch=branch, status="queued")
        db.add(active)
        _queue_job(db, repo, branch, user.id, "index:manual", active)
        indexing_service.get_state(db, repo.id, branch).status = "queued"
        if branch == repo.default_branch:
            repo.index_status, repo.index_error = "queued", None
        db.add(AuditLog(user_id=user.id, action="repository.index_requested", target_type="repository", target_id=str(repo.id), meta={"branch": branch}))
        db.commit()
    return _status(db, repo, s, branch)


@router.post("/{repository_id}/index/retry-failed", response_model=IndexStatusOut, status_code=202, dependencies=[Depends(limit_index)])
def retry_failed(repository_id: int, body: IndexBranchIn | None = None, db: Session = Depends(get_db), user: User = Depends(current_user), s: Settings = Depends(settings_dep)):
    """Continue a PARTIAL index: failed batches become pending again and only the missing work is done (also continues after an exhausted embedding budget)."""
    repo = _admin_repo(db, user, repository_id, s)
    branch = (body.branch if body and body.branch else None) or repo.default_branch
    job = db.scalar(select(IndexingJob).where(IndexingJob.repository_id == repo.id, IndexingJob.branch == branch).order_by(IndexingJob.id.desc()).limit(1))
    if job is None or job.status != "partial":
        raise Conflict("There is no partial indexing run to continue for this branch.", code="nothing_to_retry")
    reset = indexing_service.retry_failed_batches(db, job)
    job.continuations += 1  # makes the queue dedup key unique, so every retry request really enqueues
    _queue_job(db, repo, branch, user.id, f"index:retry:{job.continuations}", job)
    st = indexing_service.get_state(db, repo.id, branch)
    st.status = "queued"
    db.add(AuditLog(user_id=user.id, action="repository.index_retry", target_type="repository", target_id=str(repo.id), meta={"branch": branch, "batches_reset": reset}))
    db.commit()
    return _status(db, repo, s, branch)


@router.delete("/{repository_id}/branches/{branch:path}", status_code=202, dependencies=[Depends(limit_index)])
def remove_branch_index(repository_id: int, branch: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Remove ONE branch's index (vectors + state) through the queue. The default branch's index can be removed too (re-index to restore it)."""
    repo = get_repo_for_user(db, user, repository_id, require_owner=True)
    if repo.is_demo:
        raise BadRequest("Demo repositories are sample data and cannot be indexed.", code="demo_readonly")
    st = db.scalar(select(BranchIndexState).where(BranchIndexState.repository_id == repo.id, BranchIndexState.branch == branch))
    if st is None:
        raise NotFound("This branch is not indexed.")
    if st.status == "indexing":
        raise Conflict("This branch is being indexed right now. Try again when it has finished.", code="index_running")
    job_queue.enqueue_or_requeue(db, "index_branch_delete", {"repository_id": repo.id, "branch": branch}, f"index_branch_delete:{repo.id}:{branch}")
    db.add(AuditLog(user_id=user.id, action="repository.branch_index_removed", target_type="repository", target_id=str(repo.id), meta={"branch": branch}))
    db.commit()
    return {"status": "queued"}
