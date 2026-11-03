from sqlalchemy import func, select

from app.core.config import get_settings
from app.models import IndexedFile, IndexingJob, Repository
from app.services.embedding_service import get_embedder
from app.services.github_service import GitHubClient
from app.services.indexing_service import delete_repository_index, run_index
from app.services.vector_service import get_vector_store


def handle_index(db, job) -> None:
    """Job kind 'index'. Payload: {repository_id, branch, commit?, indexing_job_id?}. Webhook pushes carry no IndexingJob row yet."""
    s = get_settings()
    p = job.payload
    ij_id = p.get("indexing_job_id")
    if not ij_id:
        repo = db.get(Repository, int(p["repository_id"]))
        ij = IndexingJob(repository_id=repo.id, branch=p.get("branch") or repo.default_branch, commit_sha=p.get("commit"), status="queued")
        db.add(ij)
        db.commit()
        ij_id = ij.id
    run_index(db, s, GitHubClient(s), get_vector_store(s), get_embedder(s), int(ij_id), deadline_seconds=max(60, job.timeout_seconds - 60))


def handle_index_delete(db, job) -> None:
    """Job kind 'index_delete' (disconnect). Skipped when the repository was reconnected meanwhile."""
    repo = db.get(Repository, int(job.payload["repository_id"]))
    if repo is None or repo.is_enabled:
        return
    had_index = (db.scalar(select(func.count()).select_from(IndexedFile).where(IndexedFile.repository_id == repo.id)) or 0) > 0 or repo.index_status != "not_indexed"
    if not had_index:
        return  # nothing was ever indexed: no vector store needed
    delete_repository_index(db, get_vector_store(get_settings()), repo.id)
