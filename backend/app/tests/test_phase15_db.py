"""Phase 3 (batch 15): branch-aware, batch-tracked, incremental partial indexing. NOT RUN in the authoring sandbox
(needs `pip install -r requirements-dev.txt`). Run: pytest -q app/tests/test_phase15_db.py"""
import hashlib

import pytest
from sqlalchemy import select

from app.tests.conftest import login
from app.tests.test_phase9_db import FILES, FakeGH, api, idx, settings  # noqa: F401  (idx and api are fixtures)


def api_error(status):
    from app.services.github_http import GitHubAPIError
    return GitHubAPIError(status)


class BranchGH(FakeGH):
    """GitHub double with several branches. branches: {name: {path: bytes}}; `broken`: paths whose blob GitHub answers 404 for."""
    def __init__(self, branches, truncated=False, broken=()):
        super().__init__({}, truncated)
        self.branches, self.broken, self.level_calls = branches, set(broken), 0
        self.commits = {self.head(b): f for b, f in branches.items()}

    @staticmethod
    def head(branch): return hashlib.sha1(branch.encode()).hexdigest()

    @staticmethod
    def _sha(b): return f"sha-{hash(b) & 0xffffff}"

    def get_branch_head(self, t, fn, b):
        if b not in self.branches: raise api_error(404)
        return self.head(b)

    def get_tree(self, t, fn, commit):
        return {"truncated": self.truncated, "tree": [] if self.truncated else [{"path": p, "type": "blob", "sha": self._sha(b), "size": len(b)} for p, b in self.commits[commit].items()]}

    def get_tree_level(self, t, fn, sha):
        self.level_calls += 1
        commit, _, prefix = sha.partition("|")
        files, seen, entries = self.commits[commit], set(), []
        for p, b in files.items():
            if not p.startswith(prefix): continue
            rest = p[len(prefix):]
            if "/" in rest:
                d = rest.split("/")[0]
                if d not in seen: seen.add(d); entries.append({"path": d, "type": "tree", "sha": f"{commit}|{prefix}{d}/"})
            else:
                entries.append({"path": rest, "type": "blob", "sha": self._sha(b), "size": len(b)})
        return {"tree": entries, "truncated": False}

    def get_blob(self, t, fn, sha, max_bytes=1_000_000):
        self.blob_calls.append(sha)
        for files in self.branches.values():
            for p, b in files.items():
                if self._sha(b) == sha:
                    if p in self.broken: raise api_error(404)
                    return b


def run_branch(ctx, gh, branch="main", **kw):
    from app.models import IndexingJob
    from app.services.indexing_service import run_index
    with ctx.db() as db:
        j = IndexingJob(repository_id=ctx.repo_id, branch=branch, status="queued"); db.add(j); db.commit()
        out = run_index(db, kw.pop("s", settings()), gh, ctx.store, ctx.emb, j.id, **kw)
        return out, j.id


def ns(ctx): return ctx.store.data.get(f"repo-{ctx.repo_id}", {})
def by_branch(ctx):
    out = {}
    for i, v in ns(ctx).items(): out.setdefault(v["metadata"]["branch"], {}).setdefault(v["metadata"]["path"], []).append(i)
    return out


def state(ctx, branch="main"):
    from app.models import BranchIndexState
    with ctx.db() as db:
        s = db.scalar(select(BranchIndexState).where(BranchIndexState.repository_id == ctx.repo_id, BranchIndexState.branch == branch))
        return None if s is None else (s.status, s.files_indexed, s.failed_batches, s.tree_incomplete, s.error)


# ---------------------------------------------------------------- branch isolation
def test_two_branches_never_collide_and_one_can_be_removed_alone(idx):
    from app.services.indexing_service import delete_branch_index
    dev = {**FILES, "app/db.py": b"def only_on_dev():\n    return 1\n"}
    gh = BranchGH({"main": FILES, "dev": dev})
    assert run_branch(idx, gh, "main")[0] == "completed" and run_branch(idx, gh, "dev")[0] == "completed"
    b = by_branch(idx)
    assert set(b) == {"main", "dev"} and "app/db.py" in b["main"] and "app/db.py" in b["dev"]
    assert not set(b["main"]["app/db.py"]) & set(b["dev"]["app/db.py"])                       # same path, different branch: different vector ids
    assert all(v["metadata"]["repo_id"] == idx.repo_id for v in ns(idx).values()) and set(idx.store.data) == {f"repo-{idx.repo_id}"}
    assert state(idx, "main")[0] == "indexed" and state(idx, "dev")[0] == "indexed"
    with idx.db() as db: delete_branch_index(db, idx.store, idx.repo_id, "dev")
    assert set(by_branch(idx)) == {"main"} and state(idx, "dev") is None and state(idx, "main")[0] == "indexed"   # main untouched


def test_incremental_run_on_a_branch_only_touches_that_branch(idx):
    gh = BranchGH({"main": FILES, "dev": FILES})
    run_branch(idx, gh, "main"); run_branch(idx, gh, "dev")
    before = {i for i, v in ns(idx).items() if v["metadata"]["branch"] == "main"}
    gh.branches["dev"], gh.commits = {**FILES, "extra.py": b"print('x')\n"}, {gh.head("main"): FILES, gh.head("dev"): {**FILES, "extra.py": b"print('x')\n"}}
    gh.blob_calls.clear()
    assert run_branch(idx, gh, "dev")[0] == "completed" and len(gh.blob_calls) == 1          # only the new file was fetched
    assert {i for i, v in ns(idx).items() if v["metadata"]["branch"] == "main"} == before


# ---------------------------------------------------------------- large repositories
def test_truncated_tree_is_listed_directory_by_directory_with_gitignore_and_excluded_dirs(idx):
    files = {"src/a.py": b"def a():\n    return 1\n", "src/deep/b.py": b"def b():\n    return 2\n", "node_modules/x/y.js": b"module.exports = 1\n",
             "gen/out.py": b"x = 1\n", ".gitignore": b"gen/\n"}
    gh = BranchGH({"main": files}, truncated=True)
    out, jid = run_branch(idx, gh)
    from app.models import IndexingJob
    with idx.db() as db: plan = db.get(IndexingJob, jid).plan_summary
    assert out == "completed" and set(by_branch(idx)["main"]) == {"src/a.py", "src/deep/b.py"}
    assert plan["tree"]["mode"] == "walk" and plan["tree"]["pruned_dirs"] >= 1 and plan["skipped"].get("gitignored", 0) >= 1 and gh.level_calls >= 3


def test_incomplete_tree_listing_never_deletes_indexed_files(idx):
    gh = BranchGH({"main": FILES}); run_branch(idx, gh)
    small = settings(index_max_tree_requests=1)
    gh2 = BranchGH({"main": {"app/db.py": FILES["app/db.py"], "sub/new.py": b"print(1)\n"}}, truncated=True)
    run_branch(idx, gh2, s=small)
    assert "app/web.py" in by_branch(idx)["main"] and state(idx)[3] is True                  # web.py is not in the partial listing but was NOT deleted


def test_file_limit_keeps_the_highest_priority_files_and_reports_the_rest_as_deferred(idx):
    files = {"README.md": b"# readme\n", "src/a.py": b"def a():\n    return 1\n", "src/b.py": b"def b():\n    return 2\n", "docs/x.md": b"# docs\n"}
    out, jid = run_branch(idx, BranchGH({"main": files}), s=settings(index_max_files=2))
    from app.models import BranchIndexState
    assert out == "completed" and set(by_branch(idx)["main"]) == {"src/a.py", "src/b.py"}   # code before docs, deterministic
    with idx.db() as db: st = db.scalar(select(BranchIndexState))
    assert st.files_eligible == 4 and st.files_deferred == 2


# ---------------------------------------------------------------- batches: partial failure, retry, budget, deadline
def test_a_failed_file_makes_the_run_partial_and_retry_redoes_only_that_batch(idx):
    from app.models import IndexingBatch
    from app.services.indexing_service import retry_failed_batches
    files = {"a.py": b"def a():\n    return 1\n", "b.py": b"def b():\n    return 2\n", "c.py": b"def c():\n    return 3\n"}
    gh = BranchGH({"main": files}, broken={"b.py"})
    out, jid = run_branch(idx, gh, s=settings(index_batch_files=1))
    assert out == "partial" and set(by_branch(idx)["main"]) == {"a.py", "c.py"}              # the other batches still completed
    assert state(idx)[0] == "partial" and state(idx)[2] == 1 and repo_status(idx) == "partial"
    with idx.db() as db:
        failed = db.scalars(select(IndexingBatch).where(IndexingBatch.status == "failed")).all()
        assert len(failed) == 1 and [i["path"] for i in failed[0].items] == ["b.py"]
        from app.models import IndexingJob
        assert retry_failed_batches(db, db.get(IndexingJob, jid)) == 1; db.commit()
    gh.broken.clear(); gh.blob_calls.clear()
    from app.services.indexing_service import run_index
    with idx.db() as db:
        assert run_index(db, settings(index_batch_files=1), gh, idx.store, idx.emb, jid) == "completed"
    assert len(gh.blob_calls) == 1 and set(by_branch(idx)["main"]) == {"a.py", "b.py", "c.py"} and state(idx)[0] == "indexed"   # only b.py was fetched again


def repo_status(ctx):
    from app.models import Repository
    with ctx.db() as db: return db.get(Repository, ctx.repo_id).index_status


def test_embedding_budget_stops_the_run_as_partial_and_it_can_be_continued(idx):
    from app.models import IndexingJob
    from app.services.indexing_service import retry_failed_batches, run_index
    files = {f"f{i}.py": f"def f{i}():\n    return {i}\n".encode() for i in range(4)}
    s = settings(index_batch_files=1, index_max_chunks_per_run=1)
    out, jid = run_branch(idx, BranchGH({"main": files}), s=s)
    assert out == "partial" and 0 < len(by_branch(idx)["main"]) < 4 and "Embedding budget" in state(idx)[4]
    with idx.db() as db:
        retry_failed_batches(db, db.get(IndexingJob, jid)); db.commit()
    done = 0
    for _ in range(6):
        with idx.db() as db: out = run_index(db, s, BranchGH({"main": files}), idx.store, idx.emb, jid)
        if out == "completed": break
        with idx.db() as db: retry_failed_batches(db, db.get(IndexingJob, jid)); db.commit()
    assert out == "completed" and len(by_branch(idx)["main"]) == 4


def test_deadline_saves_progress_and_the_same_job_continues(idx):
    from app.models import IndexingBatch, IndexingJob
    from app.services.indexing_service import IndexDeadline, run_index
    files = {f"f{i}.py": f"def f{i}():\n    return {i}\n".encode() for i in range(3)}
    gh = BranchGH({"main": files})
    with pytest.raises(IndexDeadline): run_branch(idx, gh, s=settings(index_batch_files=1), deadline_seconds=-1)
    with idx.db() as db:
        jid = db.scalar(select(IndexingJob.id)); j = db.get(IndexingJob, jid)
        assert j.status == "queued" and db.scalar(select(IndexingBatch.id).where(IndexingBatch.status == "pending")) is not None
        assert run_index(db, settings(index_batch_files=1), gh, idx.store, idx.emb, jid) == "completed"   # same job resumes from its saved batches
    assert len(by_branch(idx)["main"]) == 3


# ---------------------------------------------------------------- branch lifecycle
def test_missing_branch_is_marked_and_nothing_is_deleted_automatically(idx):
    gh = BranchGH({"main": FILES, "dev": FILES}); run_branch(idx, gh, "dev")
    before = dict(by_branch(idx)["dev"])
    out, _ = run_branch(idx, BranchGH({"main": FILES}), "dev")                                # branch deleted/renamed/no access: GitHub answers 404
    assert out == "cancelled" and state(idx, "dev")[0] == "missing" and "not found" in state(idx, "dev")[4]
    assert by_branch(idx)["dev"] == before                                                    # vectors stay until an admin (or GitHub's delete event) removes them


def test_legacy_vectors_are_replaced_by_branch_aware_ones_on_the_first_run(idx):
    from app.models import IndexedFile
    from app.services.index_policy import namespace_for, path_hash, vector_id
    gh = BranchGH({"main": FILES}); run_branch(idx, gh)                                       # build realistic new-format data first
    with idx.db() as db:                                                                      # then rewrite it into the OLD format
        for f in db.scalars(select(IndexedFile)).all():
            f.vector_schema = 1
            for i in range(f.chunk_count):
                new_id, old_id = vector_id(f.path, i, "main"), vector_id(f.path, i)
                idx.store.data[namespace_for(idx.repo_id)][old_id] = idx.store.data[namespace_for(idx.repo_id)].pop(new_id)
        db.commit()
    assert all("#" in i and ":" not in i for i in ns(idx))
    gh.blob_calls.clear()
    assert run_branch(idx, gh)[0] == "completed" and len(gh.blob_calls) == 3                  # re-embedded although the blob SHAs are unchanged
    assert all(":" in i for i in ns(idx)) and not any(i.startswith(path_hash("app/db.py") + "#") for i in ns(idx))   # legacy ids gone, no duplicates
    with idx.db() as db: assert {f.vector_schema for f in db.scalars(select(IndexedFile)).all()} == {2}


# ---------------------------------------------------------------- API: branches, search, retry, removal
def use_gh(api, gh):
    api.app.dependency_overrides[api.deps.get_github_client] = lambda: gh
    return gh


def test_search_is_branch_scoped_and_explains_unknown_branches(api):
    gh = BranchGH({"main": FILES, "dev": {**FILES, "app/db.py": b"def only_on_dev_branch():\n    return 1\n"}})
    run_branch(api, gh, "main"); run_branch(api, gh, "dev")
    c, csrf = login(api); h = {"X-CSRF-Token": csrf}
    b = c.get("/api/v1/code-search/branches").json()["branches"]
    assert [x["branch"] for x in b] == ["main", "dev"] and b[0]["is_default_somewhere"] is True and b[1]["is_default_somewhere"] is False
    r = c.post("/api/v1/code-search/query", json={"query": "only on dev branch", "branch": "dev"}, headers=h).json()
    assert r["branch"] == "dev" and r["results"] and all(x["branch"] == "dev" for x in r["results"])
    d = c.post("/api/v1/code-search/query", json={"query": "open connection pool"}, headers=h).json()   # no branch: the default branch of each repository
    assert d["results"] and all(x["branch"] == "main" for x in d["results"])
    g = c.post("/api/v1/code-search/query", json={"query": "open connection", "branch": "ghost"}, headers=h).json()
    assert g["results"] == [] and "None of your repositories is indexed on branch 'ghost'" in g["note"]   # deleted/renamed/unknown: explained, not an error


def test_start_index_validates_the_branch_and_limits_extra_branches(api, monkeypatch):
    gh = use_gh(api, BranchGH({"main": FILES, "dev": FILES, "qa": FILES}))
    monkeypatch.setenv("INDEX_MAX_BRANCHES", "1")
    from app.core.config import get_settings; get_settings.cache_clear()
    c, csrf = login(api); h = {"X-CSRF-Token": csrf}
    base = f"/api/v1/repositories/{api.repo_id}"
    assert c.post(f"{base}/index", json={"branch": "ghost"}, headers=h).status_code == 404         # not on GitHub
    r = c.post(f"{base}/index", json={"branch": "dev"}, headers=h)
    assert r.status_code == 202 and r.json()["branch"] == "dev" and r.json()["status"] == "queued"
    assert c.post(f"{base}/index", json={"branch": "dev"}, headers=h).json()["job"]["id"] == r.json()["job"]["id"]   # double click reuses the job
    over = c.post(f"{base}/index", json={"branch": "qa"}, headers=h)
    assert over.status_code == 400 and over.json()["error"]["code"] == "too_many_branches"
    assert c.post(f"{base}/index", json={"branch": "bad branch!"}, headers=h).status_code == 422     # validated, never used as a path


def test_retry_failed_needs_a_partial_run_and_branch_removal_goes_through_the_queue(api):
    from app.models import BackgroundJob
    gh = use_gh(api, BranchGH({"main": FILES, "dev": FILES})); run_branch(api, gh, "dev")
    c, csrf = login(api); h = {"X-CSRF-Token": csrf}
    base = f"/api/v1/repositories/{api.repo_id}"
    assert c.post(f"{base}/index/retry-failed", json={"branch": "dev"}, headers=h).json()["error"]["code"] == "nothing_to_retry"
    assert c.delete(f"{base}/branches/ghost", headers=h).status_code == 404
    assert c.delete(f"{base}/branches/dev", headers=h).status_code == 202
    with api.db() as db: assert db.scalar(select(BackgroundJob).where(BackgroundJob.kind == "index_branch_delete")) is not None
    assert c.delete(f"{base}/branches/dev").status_code == 403                                      # CSRF


def test_push_webhook_refreshes_tracked_branches_and_cleans_up_deleted_ones(idx):
    from app.models import BackgroundJob, Repository, ReviewConfiguration
    from app.services.webhook_service import _on_push
    run_branch(idx, BranchGH({"main": FILES, "dev": FILES}), "dev")                 # dev is now a tracked (indexed) branch
    with idx.db() as db:
        repo = db.get(Repository, idx.repo_id); repo.is_enabled = True
        if repo.config is None: repo.config = ReviewConfiguration()
        db.commit()
        gid = repo.github_repo_id
        ev = lambda ref, after="d" * 40, deleted=False: {"ref": ref, "after": after, "deleted": deleted, "repository": {"id": gid, "default_branch": repo.default_branch}}
        assert _on_push(db, ev("refs/heads/dev"))[0] == "queued"                      # tracked branch: incremental refresh
        assert _on_push(db, ev("refs/heads/feature-x"))[0] == "ignored"               # branch nobody indexed
        assert _on_push(db, ev("refs/tags/v1"))[0] == "ignored"
        assert _on_push(db, ev("refs/heads/dev", deleted=True))[0] == "queued"        # GitHub deleted it: its vectors/state are removed
        assert _on_push(db, ev("refs/heads/main"))[0] == "queued"                     # default branch behaves as before
        db.commit()
        kinds = sorted((j.kind, j.payload.get("branch")) for j in db.scalars(select(BackgroundJob)).all())
    assert kinds == [("index", "dev"), ("index", "main"), ("index_branch_delete", "dev")]
