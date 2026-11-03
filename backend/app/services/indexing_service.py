"""Incremental repository indexing. Per file: fetch blob -> chunk -> drop secret chunks -> embed -> upsert, then
remove stale vectors. Progress (IndexedFile rows) is committed as it goes, so a timeout/retry resumes where it stopped."""
import time

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import BadRequest
from app.db.base import utcnow
from app.models import AuditLog, IndexedFile, IndexingJob, Repository
from app.services.chunking import chunk_source
from app.services.embedding_service import check_dimensions
from app.services.index_policy import decode_text, drop_secret_chunks, file_prefix, namespace_for, plan_index, vector_id
from app.services.job_policy import sanitize_error
from app.services.review_context import language_of


class IndexDeadline(TimeoutError):
    pass


def _fail(db: Session, job: IndexingJob, repo: Repository, exc, *, will_retry: bool) -> None:
    db.rollback()
    job, repo = db.get(IndexingJob, job.id), db.get(Repository, repo.id)
    msg = sanitize_error(exc, 300)
    job.status, job.error, job.finished_at = "failed", msg, utcnow()
    repo.index_status, repo.index_error = "failed", ("Will retry: " if will_retry else "") + msg
    db.commit()


def run_index(db: Session, s: Settings, gh, store, embedder, job_id: int, *, deadline_seconds: float = 1700.0) -> str:
    job = db.get(IndexingJob, job_id)
    repo = db.get(Repository, job.repository_id)
    cfg = repo.config
    if not repo.is_enabled or (cfg and not cfg.index_enabled):
        job.status, job.error, job.finished_at = "cancelled", "Repository is disconnected or indexing is disabled", utcnow()
        db.commit()
        return "cancelled"
    started = time.monotonic()
    job.status, job.started_at, job.error = "indexing", utcnow(), None
    repo.index_status, repo.index_error = "indexing", None
    db.commit()
    try:
        store.check()
        from app.models import GitHubInstallation
        token = gh.installation_token(db.get(GitHubInstallation, repo.installation_id).installation_id)
        commit = job.commit_sha or gh.get_branch_head(token, repo.full_name, job.branch)
        tree = gh.get_tree(token, repo.full_name, commit)
        if tree.get("truncated"):
            raise BadRequest("This repository is too large for GitHub's recursive tree API (truncated). Indexing was not started.", code="tree_truncated")
        existing = {f.path: f.blob_sha for f in db.scalars(select(IndexedFile).where(IndexedFile.repository_id == repo.id)).all()}
        plan = plan_index(existing, tree.get("tree", []), max_bytes=s.index_max_file_bytes, max_files=s.index_max_files)
        job.commit_sha, job.files_total = commit, len(plan["to_index"]) + len(plan["to_delete"])
        db.commit()
        ns = namespace_for(repo.id)
        for path in plan["to_delete"]:
            _delete_file(db, store, repo.id, ns, path)
            job.files_indexed += 1
            db.commit()
        for entry in plan["to_index"]:
            if time.monotonic() - started > deadline_seconds:
                raise IndexDeadline("Indexing exceeded its time budget; it will resume incrementally")
            job.chunks_upserted += _index_file(db, s, gh, store, embedder, token, repo, job, ns, commit, entry)
            job.files_indexed += 1
            db.commit()
    except Exception as exc:  # noqa: BLE001
        _fail(db, job, repo, exc, will_retry=True)
        raise
    job, repo = db.get(IndexingJob, job_id), db.get(Repository, repo.id)
    job.status, job.finished_at = "completed", utcnow()
    repo.index_status, repo.last_indexed_at, repo.last_indexed_commit, repo.index_error = "indexed", utcnow(), commit, None
    db.add(AuditLog(action="repository.indexed", target_type="repository", target_id=str(repo.id),
                    meta={"commit": commit[:12], "files": job.files_indexed, "chunks": job.chunks_upserted, "skipped": plan["skipped"], "limited": plan["limited"]}))
    db.commit()
    return "completed"


def _delete_file(db: Session, store, repo_id: int, ns: str, path: str) -> None:
    store.delete_ids(ns, store.list_ids(ns, file_prefix(path)))
    db.execute(delete(IndexedFile).where(IndexedFile.repository_id == repo_id, IndexedFile.path == path))


def _index_file(db, s, gh, store, embedder, token, repo, job, ns, commit, entry) -> int:
    path = entry["path"]
    raw = gh.get_blob(token, repo.full_name, entry["sha"], s.index_max_file_bytes)
    text = decode_text(raw) if raw is not None else None
    chunks, _ = drop_secret_chunks(chunk_source(text, language_of(path), max_chars=s.index_chunk_chars), text) if text else ([], 0)
    new_ids = [vector_id(path, i) for i in range(len(chunks))]
    lang = language_of(path)
    for i in range(0, len(chunks), s.index_embed_batch):
        batch = chunks[i:i + s.index_embed_batch]
        vectors = embedder.embed([f"{path}\n{c.text}" for c in batch])
        check_dimensions(vectors, s.embedding_dimensions)
        store.upsert(ns, [{"id": new_ids[i + j], "values": vec, "metadata": {
            "repo_id": repo.id, "repository": repo.full_name, "branch": job.branch, "commit": commit, "path": path, "language": lang or "",
            "start_line": c.start_line, "end_line": c.end_line, "text": c.text[:1500]}} for j, (c, vec) in enumerate(zip(batch, vectors))])
    stale = set(store.list_ids(ns, file_prefix(path))) - set(new_ids)  # after upsert: no window without data
    if stale:
        store.delete_ids(ns, sorted(stale))
    row = db.scalar(select(IndexedFile).where(IndexedFile.repository_id == repo.id, IndexedFile.path == path))
    if row is None:
        row = IndexedFile(repository_id=repo.id, path=path, blob_sha=entry["sha"])
        db.add(row)
    row.blob_sha, row.chunk_count, row.commit_sha, row.indexed_at = entry["sha"], len(chunks), commit, utcnow()
    return len(chunks)


def delete_repository_index(db: Session, store, repo_id: int) -> None:
    """Disconnect cleanup: drop the repository's whole namespace and its index state."""
    store.delete_namespace(namespace_for(repo_id))
    db.execute(delete(IndexedFile).where(IndexedFile.repository_id == repo_id))
    repo = db.get(Repository, repo_id)
    if repo is not None:
        repo.index_status, repo.last_indexed_at, repo.last_indexed_commit, repo.index_error = "not_indexed", None, None, None
    db.commit()
