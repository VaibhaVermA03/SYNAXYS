from datetime import timedelta

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.exceptions import RateLimited
from app.db.base import utcnow
from app.models import BranchIndexState, IndexedFile, IndexingJob, Repository
from app.services import job_queue
from app.services.embedding_service import get_embedder
from app.services.github_service import GitHubClient
from app.services.indexing_service import IndexDeadline, delete_branch_index, delete_repository_index, run_index
from app.services.vector_service import get_vector_store

BUSY_WINDOW = timedelta(minutes=35)  # a job 'indexing' for longer than its own timeout is treated as dead, not busy


def handle_index(db, job) -> None:
    """Job kind 'index'. Payload: {repository_id, branch, commit?, indexing_job_id?}. Webhook pushes carry no IndexingJob row yet.
    A run that used up its time slice is continued by a new queue job for the SAME IndexingJob (its batches persist)."""
    s = get_settings()
    p = job.payload
    ij_id = p.get("indexing_job_id")
    if not ij_id:
        repo = db.get(Repository, int(p["repository_id"]))
        ij = IndexingJob(repository_id=repo.id, branch=p.get("branch") or repo.default_branch, commit_sha=p.get("commit"), status="queued")
        db.add(ij)
        db.commit()
        ij_id = ij.id
    ij = db.get(IndexingJob, int(ij_id))
    other = db.scalar(select(IndexingJob.id).where(IndexingJob.repository_id == ij.repository_id, IndexingJob.branch == ij.branch, IndexingJob.status == "indexing",
                                                   IndexingJob.id != ij.id, IndexingJob.started_at > utcnow() - BUSY_WINDOW))
    if other is not None:  # never two writers for one branch: retry later with the queue's backoff
        raise RateLimited("Another indexing run for this branch is active; retrying later.", code="index_busy")
    try:
        run_index(db, s, GitHubClient(s), get_vector_store(s), get_embedder(s), int(ij_id), deadline_seconds=max(60, job.timeout_seconds - 60))
    except IndexDeadline:
        ij = db.get(IndexingJob, int(ij_id))
        if ij.continuations >= s.index_max_continuations:
            ij.status, ij.error = "partial", "Too many continuations; continue indexing manually."
            db.commit()
            return
        ij.continuations += 1
        job_queue.enqueue(db, "index", {"repository_id": ij.repository_id, "branch": ij.branch, "indexing_job_id": ij.id}, f"index:cont:{ij.id}:{ij.continuations}", timeout_seconds=1800)
        db.commit()


def handle_index_delete(db, job) -> None:
    """Job kind 'index_delete' (disconnect). Skipped when the repository was reconnected meanwhile."""
    if job.payload.get("purged"):  # the repository row was deleted together with its workspace: remove its namespace by id
        delete_repository_index(db, get_vector_store(get_settings()), int(job.payload["repository_id"]))
        return
    repo = db.get(Repository, int(job.payload["repository_id"]))
    if repo is None or repo.is_enabled:
        return
    had_index = (db.scalar(select(func.count()).select_from(IndexedFile).where(IndexedFile.repository_id == repo.id)) or 0) > 0 or repo.index_status != "not_indexed" \
        or (db.scalar(select(func.count()).select_from(BranchIndexState).where(BranchIndexState.repository_id == repo.id)) or 0) > 0
    if not had_index:
        return  # nothing was ever indexed: no vector store needed
    delete_repository_index(db, get_vector_store(get_settings()), repo.id)


def handle_index_branch_delete(db, job) -> None:
    """Job kind 'index_branch_delete': a branch was deleted on GitHub (webhook) or an admin removed its index. Only that branch is touched."""
    repo = db.get(Repository, int(job.payload["repository_id"]))
    branch = str(job.payload["branch"])
    if repo is None:
        return
    has = db.scalar(select(BranchIndexState.id).where(BranchIndexState.repository_id == repo.id, BranchIndexState.branch == branch))
    if has is None:
        return
    delete_branch_index(db, get_vector_store(get_settings()), repo.id, branch)
