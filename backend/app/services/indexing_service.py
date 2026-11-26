"""Branch-aware, batch-tracked, incremental repository indexing (Phase 3).

Flow of one run (`run_index`, one IndexingJob = one branch):
  1. PLAN (only when the job has no batches yet): resolve the branch head -> list the tree (recursive; if GitHub reports it truncated, directory by
     directory with excluded directories never fetched) -> apply exclusions (binary/generated/vendored/secret-named, root .gitignore, per-repository
     include/exclude globs, size) -> rank by priority and cut at the file limit -> compare blob SHAs with what is indexed for THIS branch ->
     persist the work as `indexing_batches` (a few files each).
  2. EXECUTE pending batches in order. Per file: fetch blob -> chunk -> drop secret chunks -> embed -> upsert -> delete stale vectors -> commit.
     A file that fails for a file-specific reason (blob gone/too large for GitHub) marks only its batch `failed` (the rest of the run continues);
     provider/outage errors abort the run and the queue retries it - finished batches are never redone.
  3. FINISH: all batches done -> `completed`/`indexed`; failed batches or an exhausted embedding budget -> `partial` (searchable; "retry failed" resumes
     only the missing work). A run that hits its time slice raises IndexDeadline after saving progress; the worker enqueues a continuation.
Vector ids and metadata carry the branch (`<branchtag>:<pathhash>#<n>`), namespaces stay one per repository (`repo-<id>`), and every query/delete is scoped to
that namespace. Deleting a file removes its vectors; an INCOMPLETE tree listing never deletes anything.
"""
import logging
import time

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import utcnow
from app.models import AuditLog, BranchIndexState, GitHubInstallation, IndexedFile, IndexingBatch, IndexingJob, Repository
from app.services.chunking import chunk_source
from app.services.embedding_service import check_dimensions
from app.services.github_http import GitHubAPIError
from app.services.gitignore import GitIgnore
from app.services.index_policy import (branch_prefix, decode_text, dir_excluded_factory, drop_secret_chunks, file_prefix, make_batches, namespace_for, plan_index,
                                       vector_id)
from app.services import notification_service
from app.services.job_policy import sanitize_error
from app.services.review_context import language_of
from app.services.tree_walk import walk_tree

log = logging.getLogger("synaxys.indexing")
FILE_LEVEL_STATUSES = (404, 409, 410, 422, 451)  # GitHub answers that concern one blob, not the whole run


class IndexDeadline(TimeoutError):
    pass


def _c(s, name, default):
    return getattr(s, name, default)  # tolerant of minimal settings objects


# ---- state helpers -----------------------------------------------------------------------------------------------
def get_state(db: Session, repo_id: int, branch: str) -> BranchIndexState:
    st = db.scalar(select(BranchIndexState).where(BranchIndexState.repository_id == repo_id, BranchIndexState.branch == branch))
    if st is None:
        st = BranchIndexState(repository_id=repo_id, branch=branch, status="queued")
        db.add(st)
        db.flush()
    return st


def _mirror(repo: Repository, branch: str, status: str, error: str | None, commit: str | None = None, indexed_at=None) -> None:
    """Repository.index_* keeps describing the DEFAULT branch (existing UI/API contract)."""
    if branch != repo.default_branch:
        return
    repo.index_status, repo.index_error = status, error
    if commit:
        repo.last_indexed_commit = commit
    if indexed_at:
        repo.last_indexed_at = indexed_at


def _fail(db: Session, job: IndexingJob, repo: Repository, branch: str, exc, *, will_retry: bool) -> None:
    db.rollback()
    job, repo = db.get(IndexingJob, job.id), db.get(Repository, repo.id)
    msg = sanitize_error(exc, 300)
    job.status, job.error, job.finished_at = "failed", msg, utcnow()
    st = get_state(db, repo.id, branch)
    st.status, st.error = "failed", (("Will retry: " if will_retry else "") + msg)[:500]
    _mirror(repo, branch, "failed", ("Will retry: " if will_retry else "") + msg)
    db.commit()


def _release_for_continuation(db: Session, job: IndexingJob, repo: Repository, branch: str) -> None:
    job.status = "queued"  # progress is saved; the worker enqueues a continuation of THIS job
    st = get_state(db, repo.id, branch)
    st.status = "indexing"
    _mirror(repo, branch, "indexing", None)
    db.commit()


# ---- tree + .gitignore ---------------------------------------------------------------------------------------------
def _load_gitignore(gh, token, repo, s, entries) -> GitIgnore | None:
    if not _c(s, "index_respect_gitignore", True):
        return None
    for e in entries:
        if e.get("type") == "blob" and e["path"] == ".gitignore":
            try:
                raw = gh.get_blob(token, repo.full_name, e["sha"], 100_000)
                text = decode_text(raw) if raw is not None else None
                return GitIgnore(text) if text else None
            except GitHubAPIError:
                return None  # an unreadable .gitignore must not stop indexing
    return None


def _list_tree(gh, token, repo, commit, s, cfg) -> tuple[list[dict], dict, GitIgnore | None]:
    exclude = list(getattr(cfg, "index_exclude_globs", None) or []) if cfg else []
    tree = gh.get_tree(token, repo.full_name, commit)
    if not tree.get("truncated"):
        entries = tree.get("tree", [])
        return entries, {"mode": "recursive", "incomplete": False}, _load_gitignore(gh, token, repo, s, entries)
    root = gh.get_tree_level(token, repo.full_name, commit)  # GitHub refused the recursive listing: walk directory by directory
    ignore = _load_gitignore(gh, token, repo, s, root.get("tree", []))
    entries, stats = walk_tree(
        lambda sha: gh.get_tree_level(token, repo.full_name, sha),
        commit,
        dir_excluded=dir_excluded_factory(ignore, exclude),
        dir_excluded_reason=lambda path: "gitignored" if ignore is not None and ignore.ignored(path, is_dir=True) else None,
        max_requests=_c(s, "index_max_tree_requests", 400),
    )
    return entries, {"mode": "walk", **stats}, ignore


# ---- the run ---------------------------------------------------------------------------------------------------------
def run_index(db: Session, s: Settings, gh, store, embedder, job_id: int, *, deadline_seconds: float = 1700.0) -> str:
    job = db.get(IndexingJob, job_id)
    repo = db.get(Repository, job.repository_id)
    cfg = repo.config
    branch = job.branch or repo.default_branch
    if not repo.is_enabled or (cfg and not cfg.index_enabled):
        job.status, job.error, job.finished_at = "cancelled", "Repository is disconnected or indexing is disabled", utcnow()
        db.commit()
        return "cancelled"
    started = time.monotonic()
    state = get_state(db, repo.id, branch)
    job.status, job.started_at, job.error = "indexing", job.started_at or utcnow(), None
    state.status, state.error = "indexing", None
    _mirror(repo, branch, "indexing", None)
    db.commit()
    plan_info: dict = {}
    try:
        store.check()
        token = gh.installation_token(db.get(GitHubInstallation, repo.installation_id).installation_id)
        ns = namespace_for(repo.id)
        have_batches = (db.scalar(select(func.count()).select_from(IndexingBatch).where(IndexingBatch.job_id == job.id)) or 0) > 0
        if not have_batches:
            try:
                commit = job.commit_sha or gh.get_branch_head(token, repo.full_name, branch)
            except GitHubAPIError as exc:
                if exc.status == 404:
                    return _branch_missing(db, job, repo, branch)
                raise
            entries, tree_info, ignore = _list_tree(gh, token, repo, commit, s, cfg)
            rows = db.execute(select(IndexedFile.path, IndexedFile.blob_sha, IndexedFile.vector_schema).where(IndexedFile.repository_id == repo.id, IndexedFile.branch == branch)).all()
            existing = {p: sha for p, sha, _ in rows}
            cap = min(s.index_max_files, cfg.index_max_files) if cfg and cfg.index_max_files else s.index_max_files
            plan = plan_index(existing, entries, max_bytes=s.index_max_file_bytes, max_files=cap, ignore=ignore,
                              include_globs=list(getattr(cfg, "index_include_globs", None) or []) if cfg else [],
                              exclude_globs=list(getattr(cfg, "index_exclude_globs", None) or []) if cfg else [],
                              reindex_paths={p for p, _, v in rows if v == 1}, allow_delete=not tree_info["incomplete"])

            # Count gitignored directories pruned during truncated-tree walking.
            pruned_gitignored = int(tree_info.get("pruned_gitignored", 0))
            if pruned_gitignored:
                plan["skipped"]["gitignored"] = (
                    plan["skipped"].get("gitignored", 0) + pruned_gitignored
            )
                
            batches = make_batches(plan["to_index"], plan["to_delete"], batch_files=_c(s, "index_batch_files", 25), batch_bytes=_c(s, "index_batch_bytes", 2_000_000))
            for seq, b in enumerate(batches):
                db.add(IndexingBatch(job_id=job.id, seq=seq, kind=b["kind"], items=b["items"]))
            job.commit_sha, job.files_total = commit, len(plan["to_index"]) + len(plan["to_delete"])
            job.plan_summary = {"branch": branch, "tree": tree_info, "skipped": plan["skipped"], "eligible": plan["eligible"], "selected": plan["selected"],
                                "deferred": plan["deferred"], "limited": plan["limited"], "unchanged": plan["unchanged"], "batches": len(batches)}
            state.files_eligible, state.files_deferred, state.tree_incomplete = plan["eligible"], plan["deferred"], bool(tree_info["incomplete"])
            db.commit()
        commit = job.commit_sha
        plan_info = job.plan_summary or {}
        budget = _c(s, "index_max_chunks_per_run", 20_000)
        run_chunks, stopped = 0, None
        pending = db.scalars(select(IndexingBatch).where(IndexingBatch.job_id == job.id, IndexingBatch.status == "pending").order_by(IndexingBatch.seq)).all()
        for batch in pending:
            if time.monotonic() - started > deadline_seconds:
                raise IndexDeadline("Indexing reached its time slice; it continues from the next pending batch")
            if run_chunks >= budget:
                stopped = "budget"
                break
            run_chunks += _run_batch(db, s, gh, store, embedder, token, repo, job, ns, commit, batch, branch, started, deadline_seconds)
    except IndexDeadline:
        _release_for_continuation(db, job, repo, branch)
        raise
    except Exception as exc:  # noqa: BLE001
        _fail(db, job, repo, branch, exc, will_retry=True)
        raise
    return _finish(db, job_id, repo.id, branch, stopped, plan_info)


def _run_batch(db, s, gh, store, embedder, token, repo, job, ns, commit, batch: IndexingBatch, branch: str, started: float, deadline_seconds: float) -> int:
    items = list(batch.items)
    batch.attempts += 1
    failed: list[dict] = []
    last_error = None
    chunks = 0
    for idx, item in enumerate(items):
        if time.monotonic() - started > deadline_seconds:
            batch.items = items[idx:] + failed  # what is left (kept pending) plus files that already failed
            db.commit()
            raise IndexDeadline("Indexing reached its time slice; it continues from the next pending batch")
        try:
            if batch.kind == "delete":
                _delete_file(db, store, repo.id, ns, branch, item["path"])
            else:
                n = _index_file(db, s, gh, store, embedder, token, repo, ns, commit, item, branch)
                chunks += n
                job.chunks_upserted += n
                batch.chunks += n
        except GitHubAPIError as exc:
            if exc.status not in FILE_LEVEL_STATUSES:
                raise
            db.rollback()
            job, batch = db.get(IndexingJob, job.id), db.get(IndexingBatch, batch.id)
            failed.append(item)
            last_error = f"GitHub {exc.status} for one file"
            continue
        job.files_indexed += 1
        batch.files_done += 1
        db.commit()
    batch.items = failed
    batch.status, batch.error = ("failed", f"{len(failed)} file(s) failed: {last_error}") if failed else ("done", None)
    db.commit()
    return chunks


def _finish(db: Session, job_id: int, repo_id: int, branch: str, stopped: str | None, plan_info: dict) -> str:
    job, repo = db.get(IndexingJob, job_id), db.get(Repository, repo_id)
    counts = dict(db.execute(select(IndexingBatch.status, func.count()).where(IndexingBatch.job_id == job.id).group_by(IndexingBatch.status)).all())
    pending, failed = counts.get("pending", 0), counts.get("failed", 0)
    st = get_state(db, repo.id, branch)
    now = utcnow()
    st.files_indexed = db.scalar(select(func.count()).select_from(IndexedFile).where(IndexedFile.repository_id == repo.id, IndexedFile.branch == branch)) or 0
    st.failed_batches = failed
    job.finished_at = now
    if pending == 0 and failed == 0:
        job.status, job.error = "completed", None
        st.status, st.error, st.last_indexed_commit, st.last_indexed_at = "indexed", None, job.commit_sha, now
        _mirror(repo, branch, "indexed", None, job.commit_sha, now)
        outcome = "completed"
    else:
        reason = "Embedding budget for one run reached; continue indexing to finish." if (pending and stopped == "budget") else f"{failed} batch(es) failed; retry the failed batches." if failed else f"{pending} batch(es) still pending."
        job.status, job.error = "partial", reason
        st.status, st.error, st.last_indexed_commit, st.last_indexed_at = "partial", reason, job.commit_sha, now
        _mirror(repo, branch, "partial", reason, job.commit_sha, now)
        outcome = "partial"
    db.add(AuditLog(action="repository.indexed", target_type="repository", target_id=str(repo.id),
                    meta={"branch": branch, "commit": (job.commit_sha or "")[:12], "files": job.files_indexed, "chunks": job.chunks_upserted, "outcome": outcome,
                          "skipped": plan_info.get("skipped", {}), "deferred": plan_info.get("deferred", 0), "limited": plan_info.get("limited", False)}))
    notification_service.safe(notification_service.on_index_finished, db, repo, branch, outcome, job)
    db.commit()
    return outcome


def _branch_missing(db: Session, job: IndexingJob, repo: Repository, branch: str) -> str:
    """GitHub says the branch does not exist (deleted, renamed, or the app lost access). Nothing is deleted automatically: the index of that
    branch is marked 'missing' and excluded from search until the branch returns or an admin removes the branch index."""
    msg = f"Branch '{branch}' was not found on GitHub (deleted, renamed or no longer accessible)."
    job.status, job.error, job.finished_at = "cancelled", msg, utcnow()
    st = get_state(db, repo.id, branch)
    st.status, st.error = "missing", msg
    _mirror(repo, branch, "failed", msg)
    db.commit()
    return "cancelled"


def retry_failed_batches(db: Session, job: IndexingJob) -> int:
    """failed -> pending (only the files that still need work are in `items`). Returns how many batches were reset."""
    batches = db.scalars(select(IndexingBatch).where(IndexingBatch.job_id == job.id, IndexingBatch.status == "failed")).all()
    for b in batches:
        b.status, b.error = "pending", None
    if batches or job.status == "partial":
        job.status, job.error, job.finished_at = "queued", None, None
    return len(batches)


# ---- deletion --------------------------------------------------------------------------------------------------------
def _delete_file(db: Session, store, repo_id: int, ns: str, branch: str, path: str) -> None:
    row = db.scalar(select(IndexedFile).where(IndexedFile.repository_id == repo_id, IndexedFile.branch == branch, IndexedFile.path == path))
    ids = set(store.list_ids(ns, file_prefix(path, branch)))
    if row is not None and row.vector_schema == 1:
        ids |= set(store.list_ids(ns, file_prefix(path)))  # legacy ids (only the default branch ever had them)
    store.delete_ids(ns, sorted(ids))
    db.execute(delete(IndexedFile).where(IndexedFile.repository_id == repo_id, IndexedFile.branch == branch, IndexedFile.path == path))


def _index_file(db, s, gh, store, embedder, token, repo, ns, commit, entry, branch) -> int:
    path = entry["path"]
    raw = gh.get_blob(token, repo.full_name, entry["sha"], s.index_max_file_bytes)
    text = decode_text(raw) if raw is not None else None
    lang = language_of(path)
    chunks, _ = drop_secret_chunks(chunk_source(text, lang, max_chars=s.index_chunk_chars), text) if text else ([], 0)
    new_ids = [vector_id(path, i, branch) for i in range(len(chunks))]
    for i in range(0, len(chunks), s.index_embed_batch):
        batch = chunks[i:i + s.index_embed_batch]
        vectors = embedder.embed([f"{path}\n{c.text}" for c in batch])
        check_dimensions(vectors, s.embedding_dimensions)
        store.upsert(ns, [{"id": new_ids[i + j], "values": vec, "metadata": {
            "repo_id": repo.id, "repository": repo.full_name, "branch": branch, "commit": commit, "path": path, "language": lang or "",
            "start_line": c.start_line, "end_line": c.end_line, "text": c.text[:1500]}} for j, (c, vec) in enumerate(zip(batch, vectors))])
    row = db.scalar(select(IndexedFile).where(IndexedFile.repository_id == repo.id, IndexedFile.branch == branch, IndexedFile.path == path))
    if row is not None:  # stale chunks are known exactly (ids are deterministic), so no per-file list call is needed
        stale = [vector_id(path, i, branch) for i in range(len(chunks), row.chunk_count)] if row.vector_schema != 1 else [vector_id(path, i) for i in range(row.chunk_count)]
        if stale:
            store.delete_ids(ns, stale)  # after the upsert: there is never a window without data
    else:
        row = IndexedFile(repository_id=repo.id, branch=branch, path=path, blob_sha=entry["sha"])
        db.add(row)
    row.blob_sha, row.chunk_count, row.commit_sha, row.indexed_at, row.vector_schema = entry["sha"], len(chunks), commit, utcnow(), 2
    return len(chunks)


def delete_branch_index(db: Session, store, repo_id: int, branch: str) -> None:
    """Remove ONE branch's vectors (by id prefix), file state and branch state. Other branches are untouched."""
    ns = namespace_for(repo_id)
    ids = set(store.list_ids(ns, branch_prefix(branch)))
    legacy = db.execute(select(IndexedFile.path, IndexedFile.chunk_count).where(IndexedFile.repository_id == repo_id, IndexedFile.branch == branch, IndexedFile.vector_schema == 1)).all()
    for path, n in legacy:
        ids |= {vector_id(path, i) for i in range(n)}
    store.delete_ids(ns, sorted(ids))
    db.execute(delete(IndexedFile).where(IndexedFile.repository_id == repo_id, IndexedFile.branch == branch))
    db.execute(delete(BranchIndexState).where(BranchIndexState.repository_id == repo_id, BranchIndexState.branch == branch))
    repo = db.get(Repository, repo_id)
    if repo is not None and branch == repo.default_branch:
        repo.index_status, repo.last_indexed_at, repo.last_indexed_commit, repo.index_error = "not_indexed", None, None, None
    db.commit()


def delete_repository_index(db: Session, store, repo_id: int) -> None:
    """Disconnect cleanup: drop the repository's whole namespace and ALL its index state."""
    store.delete_namespace(namespace_for(repo_id))
    db.execute(delete(IndexedFile).where(IndexedFile.repository_id == repo_id))
    db.execute(delete(BranchIndexState).where(BranchIndexState.repository_id == repo_id))
    repo = db.get(Repository, repo_id)
    if repo is not None:
        repo.index_status, repo.last_indexed_at, repo.last_indexed_commit, repo.index_error = "not_indexed", None, None, None
    db.commit()
