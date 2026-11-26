"""Phase 3 (batch 15), stdlib-only: .gitignore matcher, tree walker, branch-aware vector ids, priority/limit planning, batches, push branch parsing."""
from app.services.gitignore import GitIgnore
from app.services.index_policy import (branch_prefix, branch_tag, dir_excluded_factory, file_prefix, make_batches, path_hash, plan_index, priority, vector_id)
from app.services.tree_walk import walk_tree
from app.services.webhook_events import parse_push, push_branch


def _e(path, sha="1", size=100, typ="blob"):
    return {"path": path, "sha": sha, "size": size, "type": typ}


def test_gitignore_rules():
    g = GitIgnore("# comment\n\nnode_modules/\n*.log\n/build\ndocs/**/*.tmp\n!keep.log\nsecret?.txt\n**/cache\nsrc/*.gen.js\n")
    yes = ["node_modules/a/b.js", "a/node_modules/x.js", "x.log", "a/b/x.log", "build/out.js", "docs/a/b/c.tmp", "docs/c.tmp", "secret1.txt", "a/cache/f", "cache/f", "src/a.gen.js"]
    no = ["keep.log", "src/build/out.js", "secret12.txt", "src/x/a.gen.js", "main.py", "app/models.py"]
    assert all(g.ignored(p) for p in yes), [p for p in yes if not g.ignored(p)]
    assert not any(g.ignored(p) for p in no), [p for p in no if g.ignored(p)]
    assert g.ignored("node_modules", is_dir=True) and not g.ignored("node_modules")  # a file named like a dir-only rule is not ignored
    assert not GitIgnore("").ignored("a.py") and not GitIgnore("[unclosed\n(((").ignored("a.py")  # junk patterns never raise


def test_gitignore_cannot_reinclude_below_an_ignored_directory():
    assert GitIgnore("vendor/\n!vendor/keep.py").ignored("vendor/keep.py")


def _tree(calls):
    data = {"root": {"tree": [_e("a.py", "1"), _e("node_modules", "n", typ="tree"), _e("src", "s", typ="tree")]},
            "n": {"tree": [_e("x.js", "9")]},
            "s": {"tree": [_e("b.py", "2"), _e("deep", "d", typ="tree")]}, "d": {"tree": [_e("c.py", "3")]}}

    def fetch(sha):
        calls.append(sha)
        return data[sha]
    return fetch


def test_tree_walk_prunes_excluded_directories_without_fetching_them():
    calls = []
    entries, st = walk_tree(_tree(calls), "root", dir_excluded=lambda p: p == "node_modules", max_requests=10)
    assert [e["path"] for e in entries] == ["a.py", "src/b.py", "src/deep/c.py"] and "n" not in calls
    assert st["pruned_dirs"] == 1 and st["requests"] == 3 and not st["incomplete"]


def test_tree_walk_budget_marks_the_listing_incomplete():
    entries, st = walk_tree(_tree([]), "root", dir_excluded=lambda p: False, max_requests=2)
    assert st["request_limit_hit"] and st["incomplete"] and len(entries) < 4
    _, st2 = walk_tree(lambda sha: {"tree": [_e("f.py")], "truncated": True}, "r", dir_excluded=lambda p: False, max_requests=5)
    assert st2["truncated_dirs"] == 1 and st2["incomplete"]


def test_vector_ids_are_branch_aware_and_legacy_ids_stay_distinguishable():
    a, b = vector_id("app/db.py", 3, "main"), vector_id("app/db.py", 3, "dev")
    assert a != b and a.startswith(branch_prefix("main")) and a.startswith(file_prefix("app/db.py", "main")) and not a.startswith(branch_prefix("dev"))
    legacy = vector_id("app/db.py", 3)
    assert legacy == f"{path_hash('app/db.py')}#0003" and not a.startswith(file_prefix("app/db.py")) and not legacy.startswith(branch_prefix("main"))
    assert len(branch_tag("main")) == 8 and branch_tag("main") != branch_tag("main2")
    assert vector_id("a.py", 1, "feature/x y".replace(" ", "-")).startswith(branch_prefix("feature/x-y"))  # slashes in branch names are fine (hashed)


def test_priority_prefers_source_then_config_then_docs_and_shallow_files():
    order = sorted(["README.md", "docs/guide.md", "config.yml", "tests/test_a.py", "src/deep/er/x.py", "src/a.py", "LICENSE"], key=lambda p: priority(p, 100))
    assert order == ["src/a.py", "src/deep/er/x.py", "tests/test_a.py", "config.yml", "README.md", "docs/guide.md", "LICENSE"]
    assert priority("a.py", 100) < priority("a.py", 90_000)


def test_plan_applies_gitignore_globs_priority_limit_and_never_deletes_on_incomplete_trees():
    tree = [_e("src/a.py", "1"), _e("src/b.py", "2"), _e("README.md", "3"), _e("gen/out.py", "4"), _e("app.log", "5"), _e("tests/t.py", "6"), _e("x.bin", "7")]
    g = GitIgnore("gen/\n*.log")
    p = plan_index({}, tree, max_bytes=1000, max_files=3, ignore=g)
    assert [e["path"] for e in p["to_index"]] == ["src/a.py", "src/b.py", "tests/t.py"]            # code first, tests after production code
    assert p["skipped"] == {"gitignored": 2, "binary": 1} and p["limited"] and p["eligible"] == 4 and p["selected"] == 3 and p["deferred"] == 1
    q = plan_index({"src/a.py": "1", "gone.py": "9"}, tree, max_bytes=1000, max_files=100, ignore=g, exclude_globs=["tests/**"], include_globs=["**/*.py", "*.md"])
    assert [e["path"] for e in q["to_index"]] == ["src/b.py", "README.md"] and q["to_delete"] == ["gone.py"] and q["unchanged"] == 1
    assert q["skipped"]["excluded_by_config"] == 1
    r = plan_index({"gone.py": "9"}, tree, max_bytes=1000, max_files=100, allow_delete=False)
    assert r["to_delete"] == []                                                                     # unseen != deleted when the listing is incomplete
    s = plan_index({"src/a.py": "1"}, tree, max_bytes=1000, max_files=100, reindex_paths={"src/a.py"})
    assert "src/a.py" in [e["path"] for e in s["to_index"]]                                         # legacy-schema files are re-embedded


def test_batches_are_bounded_by_files_and_bytes_and_deletes_go_first():
    items = [_e(f"f{i}.py", str(i), 400) for i in range(7)]
    b = make_batches(items, ["x.py"], batch_files=3, batch_bytes=1000)
    assert [(x["kind"], len(x["items"])) for x in b] == [("delete", 1), ("index", 2), ("index", 2), ("index", 2), ("index", 1)]
    assert sum(len(x["items"]) for x in b if x["kind"] == "index") == 7
    big = make_batches([_e("huge.py", "1", 5000), _e("a.py", "2", 10)], [], batch_files=10, batch_bytes=1000)
    assert [len(x["items"]) for x in big] == [1, 1]
    assert make_batches([], [], batch_files=3, batch_bytes=10) == []


def test_directory_filter_skips_vendored_gitignored_and_configured_directories():
    f = dir_excluded_factory(GitIgnore("generated/"), ["docs/**"])
    assert f("node_modules") and f("a/vendor") and f("generated") and f("docs/guide") and not f("src") and not f("src/app")


def test_push_branch_parsing():
    mk = lambda ref, deleted=False: parse_push({"ref": ref, "after": "c" * 40, "deleted": deleted, "repository": {"id": 1, "default_branch": "main"}})
    assert push_branch(mk("refs/heads/dev")) == "dev" and push_branch(mk("refs/heads/feature/x-1")) == "feature/x-1"
    assert push_branch(mk("refs/tags/v1")) is None and push_branch(mk("refs/heads/a..b")) is None and push_branch(mk("refs/heads/bad name")) is None
