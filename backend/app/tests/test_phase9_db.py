"""Indexing flow + search isolation on SQLite with fakes. NOT RUN in the build sandbox (needs deps)."""
import base64
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import select

from app.services.embedding_service import HashEmbedder
from app.services.github_http import GitHubAPIError
from app.services.vector_service import InMemoryStore
from app.tests.conftest import login

SECRET = "ghp_" + "a" * 36

_LEAK = [
    f"value_{i} = {i}  # padding so this file spans several chunks"
    for i in range(1, 41)
]

_LEAK[19] = f"token = '{SECRET}'"


class FakeGH:
    def __init__(self, files, truncated=False):
        self.files, self.truncated, self.blob_calls = files, truncated, []     # files: path -> bytes
    def installation_token(self, i): return "tok"
    def get_branch_head(self, t, fn, b): return "c" * 40
    def get_tree(self, t, fn, sha):
        return {"truncated": self.truncated, "tree": [{"path": p, "type": "blob", "sha": f"sha-{hash(b) & 0xffff}", "size": len(b)} for p, b in self.files.items()]}
    def get_blob(self, t, fn, sha, max_bytes=1_000_000):
        self.blob_calls.append(sha)
        for p, b in self.files.items():
            if f"sha-{hash(b) & 0xffff}" == sha: return b
    # OAuth side for login()
    user = {"id": 1, "login": "alice"}
    def exchange_code(self, c, v): return {"access_token": "gho_x", "scope": ""}
    def get_user(self, t): return self.user
    def list_user_installations(self, t): return []
    def list_user_installation_repos(self, t, i): return []


def settings(**kw):
    base = dict(index_max_file_bytes=200_000, index_max_files=100, index_chunk_chars=300, index_embed_batch=4, embedding_dimensions=64,
                vector_backend="memory", openai_configured=False, pinecone_configured=False, context_retrieval_enabled=True, context_min_score=0.2,
                search_rate_limit_per_minute=30)
    return NS(**{**base, **kw})


FILES = {
    "app/db.py": b"def open_connection(pool):\n    return pool.acquire()\n" * 8,
    "app/web.py": b"def render_template(name):\n    return load(name)\n" * 8,
    "logo.png": b"\x89PNG\x00\x00",
    ".env": b"X=1",
    "app/leak.py": ("\n".join(_LEAK) + "\n").encode()
}


@pytest.fixture()
def idx(ctx):
    from app.models import GitHubInstallation, IndexingJob, Repository, RepositoryAccess, ReviewConfiguration, User
    with ctx.db() as db:
        u = User(github_id=1, login="alice"); db.add(u); db.flush()
        i = GitHubInstallation(installation_id=10, account_login="alice"); db.add(i); db.flush()
        r = Repository(installation_id=i.id, github_repo_id=100, full_name="alice/app", default_branch="main", is_enabled=True); r.config = ReviewConfiguration(); db.add(r); db.flush()
        db.add(RepositoryAccess(user_id=u.id, repository_id=r.id, role="owner")); db.commit()
        ctx.repo_id = r.id
    ctx.store, ctx.emb = InMemoryStore(), HashEmbedder(64)
    return ctx


def run(ctx, files, **kw):
    from app.models import IndexingJob
    from app.services.indexing_service import run_index
    with ctx.db() as db:
        j = IndexingJob(repository_id=ctx.repo_id, branch="main", status="queued"); db.add(j); db.commit()
        gh = kw.pop("gh", None) or FakeGH(files)
        out = run_index(db, kw.pop("s", settings()), gh, ctx.store, ctx.emb, j.id, **kw)
        return out, gh, j.id


def repo_state(ctx):
    from app.models import IndexedFile, Repository
    with ctx.db() as db:
        r = db.get(Repository, ctx.repo_id)
        return r.index_status, r.last_indexed_commit, r.index_error, {f.path: f.chunk_count for f in db.scalars(select(IndexedFile)).all()}


def test_initial_index_skips_binary_sensitive_and_secret_chunks(idx):
    out, gh, _ = run(idx, FILES)
    status, commit, err, files = repo_state(idx)
    assert out == "completed" and status == "indexed" and commit == "c" * 40 and err is None
    assert set(files) == {"app/db.py", "app/web.py", "app/leak.py"}                                  # png and .env never fetched
    ns = idx.store.data[f"repo-{idx.repo_id}"]
    assert ns and all(v["metadata"]["repo_id"] == idx.repo_id and v["metadata"]["branch"] == "main" and len(v["values"]) == 64 for v in ns.values())
    assert SECRET not in str(ns) and any(v["metadata"]["path"] == "app/leak.py" for v in ns.values())    # neighbours of the secret survive, the secret does not
    assert len(gh.blob_calls) == 3 and set(idx.store.data) == {f"repo-{idx.repo_id}"}


def test_incremental_reindex_only_touches_changes_and_removes_stale_vectors(idx):
    run(idx, FILES)
    changed = {**FILES, "app/db.py": b"def only_one():\n    return 1\n", "extra.py": b"print('new')\n"}
    del changed["app/web.py"]
    out, gh, _ = run(idx, changed)
    _, _, _, files = repo_state(idx)
    assert out == "completed" and set(files) == {"app/db.py", "app/leak.py", "extra.py"} and files["app/db.py"] == 1
    assert len(gh.blob_calls) == 2                                                                         # only db.py + extra.py fetched
    paths = {v["metadata"]["path"] for v in idx.store.data[f"repo-{idx.repo_id}"].values()}
    assert paths == {"app/db.py", "app/leak.py", "extra.py"}                                              # removed file's vectors are gone
    assert sum(1 for v in idx.store.data[f"repo-{idx.repo_id}"].values() if v["metadata"]["path"] == "app/db.py") == 1   # no stale chunks of old db.py


def test_failures_are_recorded_visibly_and_truncated_trees_refused(idx):
    from app.core.exceptions import BadRequest
    with pytest.raises(BadRequest): run(idx, FILES, gh=FakeGH(FILES, truncated=True))
    status, _, err, _ = repo_state(idx)
    assert status == "failed" and "too large" in err and idx.store.data == {}
    class Boom(FakeGH):
        def get_blob(self, *a, **k): raise GitHubAPIError(502)
    with pytest.raises(GitHubAPIError): run(idx, FILES, gh=Boom(FILES))
    assert repo_state(idx)[0] == "failed" and repo_state(idx)[2].startswith("Will retry")


def test_deadline_stops_cleanly_and_next_run_resumes_incrementally(idx):
    from app.services.indexing_service import IndexDeadline
    with pytest.raises(IndexDeadline): run(idx, FILES, deadline_seconds=-1)
    out, gh, _ = run(idx, FILES)
    assert out == "completed" and repo_state(idx)[0] == "indexed"


def test_disconnect_cleanup_removes_only_this_repos_namespace(idx):
    from app.models import IndexedFile
    from app.services.indexing_service import delete_repository_index
    run(idx, FILES)
    idx.store.upsert("repo-999", [{"id": "z#0", "values": [0.1] * 64, "metadata": {"repo_id": 999}}])
    with idx.db() as db: delete_repository_index(db, idx.store, idx.repo_id)
    assert f"repo-{idx.repo_id}" not in idx.store.data and "repo-999" in idx.store.data
    assert repo_state(idx) == ("not_indexed", None, None, {})


def test_enqueue_or_requeue_makes_every_disconnect_clean_up(idx):
    from app.services import job_queue as q
    from app.models import BackgroundJob
    with idx.db() as db:
        j, created = q.enqueue_or_requeue(db, "index_delete", {"repository_id": 1}, "index_delete:1"); db.commit(); assert created
        assert q.enqueue_or_requeue(db, "index_delete", {"repository_id": 1}, "index_delete:1")[1] is False      # still pending: no duplicate
        db.get(BackgroundJob, j.id).status = "succeeded"; db.commit()
        j2, again = q.enqueue_or_requeue(db, "index_delete", {"repository_id": 1}, "index_delete:1"); db.commit()
        assert again and j2.id == j.id and db.get(BackgroundJob, j.id).status == "queued"                        # second disconnect re-queues cleanup


def test_index_delete_handler_skips_when_repo_was_reconnected(idx, monkeypatch):
    from app.workers import indexing_worker
    run(idx, FILES)
    monkeypatch.setattr(indexing_worker, "get_vector_store", lambda s: idx.store)
    monkeypatch.setattr(indexing_worker, "get_settings", lambda: settings())
    with idx.db() as db:
        indexing_worker.handle_index_delete(db, NS(payload={"repository_id": idx.repo_id}))              # repo still enabled -> no-op
    assert idx.store.data
    from app.models import Repository
    with idx.db() as db:
        db.get(Repository, idx.repo_id).is_enabled = False; db.commit()
        indexing_worker.handle_index_delete(db, NS(payload={"repository_id": idx.repo_id}))
    assert not idx.store.data


# ---------------- API: search + index endpoints ----------------
@pytest.fixture()
def api(idx, monkeypatch):
    monkeypatch.setenv("VECTOR_BACKEND", "memory"); monkeypatch.setenv("EMBEDDING_DIMENSIONS", "64")
    from app.core.config import get_settings; get_settings.cache_clear()
    from app.services import vector_service, embedding_service
    idx.store = vector_service._MEMORY
    return idx


def test_search_returns_scoped_explained_linked_results_and_never_cross_tenant(api):
    run(api, FILES, s=settings())
    api.store.upsert("repo-777", [{"id": "t#0", "values": api.emb.embed(["open_connection pool acquire"])[0], "metadata": {"repo_id": 777, "path": "secret/tenant.py", "text": "open_connection pool acquire", "branch": "main"}}])
    c, csrf = login(api); h = {"X-CSRF-Token": csrf}
    r = c.post("/api/v1/code-search/query", json={"query": "open connection pool acquire"}, headers=h)
    assert r.status_code == 200
    d = r.json()
    assert d["searched_repositories"] == ["alice/app"] and d["results"][0]["path"] == "app/db.py" and "demo embeddings" in d["note"]
    assert all(x["repository"] == "alice/app" and x["path"] != "secret/tenant.py" for x in d["results"])
    assert d["results"][0]["github_url"].startswith("https://github.com/alice/app/blob/") and "code mentions" in d["results"][0]["explanation"]
    eve, ecsrf = login(api, {"id": 9, "login": "eve"})
    assert eve.post("/api/v1/code-search/query", json={"query": "open connection pool"}, headers={"X-CSRF-Token": ecsrf}).json()["results"] == []
    assert eve.post("/api/v1/code-search/query", json={"query": "open connection", "repository_id": api.repo_id}, headers={"X-CSRF-Token": ecsrf}).status_code == 404


def test_search_validation_filters_csrf_and_not_configured(api, monkeypatch):
    run(api, FILES, s=settings())
    c, csrf = login(api); h = {"X-CSRF-Token": csrf}
    assert c.post("/api/v1/code-search/query", json={"query": "pool"}).status_code == 403
    assert c.post("/api/v1/code-search/query", json={"query": "x"}, headers=h).status_code == 422
    assert c.post("/api/v1/code-search/query", json={"query": "pool", "top_k": 99}, headers=h).status_code == 422
    assert c.post("/api/v1/code-search/query", json={"query": "pool", "language": "python"}, headers=h).json()["results"]
    assert c.post("/api/v1/code-search/query", json={"query": "pool", "branch": "other"}, headers=h).json()["results"] == []
    monkeypatch.setenv("VECTOR_BACKEND", "pinecone"); monkeypatch.setenv("PINECONE_API_KEY", "")
    from app.core.config import get_settings; get_settings.cache_clear()
    r = c.post("/api/v1/code-search/query", json={"query": "pool"}, headers=h)
    assert r.status_code == 503 and r.json()["error"]["code"] == "pinecone_not_configured"


def test_index_endpoints_admin_only_dedup_and_honest_status(api, monkeypatch):
    from app.models import BackgroundJob, RepositoryAccess
    c, csrf = login(api); h = {"X-CSRF-Token": csrf}
    s0 = c.get(f"/api/v1/repositories/{api.repo_id}/index-status").json()
    assert s0["status"] == "not_indexed" and s0["available"] is True and s0["job"] is None
    r1 = c.post(f"/api/v1/repositories/{api.repo_id}/index", headers=h); assert r1.status_code == 202 and r1.json()["status"] == "queued"
    r2 = c.post(f"/api/v1/repositories/{api.repo_id}/index", headers=h); assert r2.json()["job"]["id"] == r1.json()["job"]["id"]
    with api.db() as db: assert len(db.scalars(select(BackgroundJob).where(BackgroundJob.kind == "index")).all()) == 1
    with api.db() as db: db.execute(RepositoryAccess.__table__.update().values(role="member")); db.commit()
    assert c.post(f"/api/v1/repositories/{api.repo_id}/index", headers=h).status_code == 403
    monkeypatch.setenv("VECTOR_BACKEND", "pinecone"); monkeypatch.setenv("PINECONE_API_KEY", "")
    from app.core.config import get_settings; get_settings.cache_clear()
    st = c.get(f"/api/v1/repositories/{api.repo_id}/index-status").json()
    assert st["available"] is False and st["unavailable_reason"] == "pinecone_not_configured"


def test_review_summary_reports_whether_cross_file_context_was_used(api):
    from app.models import CodeReview, PullRequest
    from app.services.review_service import execute_review
    run(api, FILES, s=settings())
    class LLM:
        model_name = "scripted"
        def __init__(self): self.user = ""
        def analyze(self, m): self.user = m[1]["content"]; return {"findings": []}
    class GH(FakeGH):
        def list_pull_request_files(self, t, fn, n): return [{"filename": "app/new.py", "status": "added", "additions": 2, "patch": "@@ -0,0 +1,2 @@\n+conn = open_connection(pool)\n+pool.acquire()"}]
    with api.db() as db:
        pr = PullRequest(repository_id=api.repo_id, number=3, title="T", author_login="b", base_branch="main", head_branch="f", head_sha="a" * 40); db.add(pr); db.flush()
        rv = CodeReview(pull_request_id=pr.id, dedup_key="k", head_sha="a" * 40, status="queued"); db.add(rv); db.commit(); rid = rv.id
    llm = LLM()
    s = settings(github_app_configured=True, review_batch_chars=24000, review_total_chars=120000, review_max_batches=6, review_max_files=50, review_max_patch_bytes=200000,
                 review_min_confidence=0.5, review_max_findings=30, openai_configured=False)
    with api.db() as db: assert execute_review(db, s, rid, GH({}), lambda _s: llm) == "completed"
    with api.db() as db: summary = db.get(CodeReview, rid).summary
    assert "Cross-file context: " in summary and "related snippet(s)" in summary and 'label="retrieved_context:app/db.py' in llm.user
