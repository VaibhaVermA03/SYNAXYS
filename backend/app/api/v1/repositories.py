"""Indexing control + status for a repository (admin to start, any member to view)."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, rate_limit, settings_dep
from app.api.v1.code_search import REASONS
from app.core.config import Settings
from app.core.exceptions import BadRequest, NotConfigured
from app.db.session import get_db
from app.models import AuditLog, IndexedFile, IndexingJob, User
from app.repositories.access import get_repo_for_user
from app.schemas.search import IndexJobOut, IndexStatusOut
from app.services import job_queue
from app.services.vector_service import indexing_available

router = APIRouter(prefix="/repositories", tags=["repositories"])
limit_index = rate_limit("index", 6)


def _iso(d):
    return d.isoformat() if d else None


def _job_out(j: IndexingJob) -> IndexJobOut:
    return IndexJobOut(id=j.id, status=j.status, commit=j.commit_sha, files_total=j.files_total, files_indexed=j.files_indexed, chunks_upserted=j.chunks_upserted,
                       error=j.error, created_at=_iso(j.created_at), started_at=_iso(j.started_at), finished_at=_iso(j.finished_at))


def _status(db: Session, repo, s: Settings) -> IndexStatusOut:
    ok, reason = indexing_available(s)
    latest = db.scalar(select(IndexingJob).where(IndexingJob.repository_id == repo.id).order_by(IndexingJob.id.desc()).limit(1))
    n = db.scalar(select(func.count()).select_from(IndexedFile).where(IndexedFile.repository_id == repo.id)) or 0
    return IndexStatusOut(status=repo.index_status, available=ok, unavailable_reason=reason, backend="memory (demo)" if s.vector_backend == "memory" else "pinecone",
                          last_indexed_at=_iso(repo.last_indexed_at), last_indexed_commit=repo.last_indexed_commit, error=repo.index_error, indexed_files=n,
                          job=_job_out(latest) if latest else None)


@router.get("/{repository_id}/index-status", response_model=IndexStatusOut)
def index_status(repository_id: int, db: Session = Depends(get_db), user: User = Depends(current_user), s: Settings = Depends(settings_dep)):
    return _status(db, get_repo_for_user(db, user, repository_id), s)


@router.post("/{repository_id}/index", response_model=IndexStatusOut, status_code=202, dependencies=[Depends(limit_index)])
def start_index(repository_id: int, db: Session = Depends(get_db), user: User = Depends(current_user), s: Settings = Depends(settings_dep)):
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
    active = db.scalar(select(IndexingJob).where(IndexingJob.repository_id == repo.id, IndexingJob.status.in_(["queued", "indexing"])))
    if active is None:  # double-clicks reuse the running job
        active = IndexingJob(repository_id=repo.id, branch=repo.default_branch, status="queued")
        db.add(active)
        db.flush()
        job_queue.enqueue(db, "index", {"repository_id": repo.id, "branch": repo.default_branch, "indexing_job_id": active.id}, f"index:manual:{active.id}", timeout_seconds=1800)
        repo.index_status, repo.index_error = "queued", None
        db.add(AuditLog(user_id=user.id, action="repository.index_requested", target_type="repository", target_id=str(repo.id)))
        db.commit()
    return _status(db, repo, s)
