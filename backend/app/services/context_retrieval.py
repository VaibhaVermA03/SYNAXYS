"""Cross-file context for reviews: nearest indexed chunks of THIS repository (its own namespace only)."""
from app.services.index_policy import namespace_for


def build_queries(files: list[dict], max_files: int = 5, max_chars: int = 800) -> list[tuple[str, str]]:
    """One query per changed file: path + added lines. Returns [(path, query_text)]."""
    out = []
    for d in files[:max_files]:
        added = [l["text"] for h in d.get("hunks", []) for l in h["lines"] if l["kind"] == "add"]
        text = (d["path"] + "\n" + "\n".join(added))[:max_chars]
        if added:
            out.append((d["path"], text))
    return out


def retrieve_context(*, repo_id: int, branch: str, changed_paths: set[str], queries: list[tuple[str, str]], store, embedder,
                     top_k: int = 3, min_score: float = 0.35, max_snippets: int = 6, max_chars_each: int = 1200) -> list[dict]:
    """Chunks of files NOT being changed (their indexed text is stale for changed files), above min_score, deduped, capped."""
    if not queries:
        return []
    vectors = embedder.embed([q for _, q in queries])
    ns, seen, found = namespace_for(repo_id), set(), []
    for vec in vectors:
        for m in store.query(ns, vec, top_k + 3, {"branch": branch}):
            meta = m["metadata"]
            key = (meta.get("path"), meta.get("start_line"))
            if m["score"] < min_score or meta.get("path") in changed_paths or key in seen or int(meta.get("repo_id", repo_id)) != repo_id:
                continue
            seen.add(key)
            found.append({"path": meta.get("path"), "start_line": meta.get("start_line"), "end_line": meta.get("end_line"),
                          "text": str(meta.get("text", ""))[:max_chars_each], "score": m["score"]})
    found.sort(key=lambda r: (-r["score"], r["path"] or ""))
    return found[:max_snippets]
