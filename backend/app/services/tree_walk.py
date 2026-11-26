"""Directory-by-directory repository tree listing for repositories whose recursive tree GitHub reports as truncated (pure; the
GitHub call is injected). Excluded directories (vendor/build/.gitignore'd) are never fetched, which is what makes huge repositories
tractable. If the request budget runs out or one directory itself is truncated the listing is INCOMPLETE and the caller must not
treat 'not listed' as 'deleted'."""
from collections import deque


def walk_tree(fetch_level, root_sha: str, *, dir_excluded, max_requests: int, dir_excluded_reason=None) -> tuple[list[dict], dict]:
    """fetch_level(tree_sha) -> {"tree": [...], "truncated": bool}. Returns (blob entries with FULL paths, stats)."""
    stats = {
    "requests": 0,
    "pruned_dirs": 0,
    "pruned_gitignored": 0,
    "truncated_dirs": 0,
    "request_limit_hit": False,
    "incomplete": False,
}
    entries: list[dict] = []
    queue = deque([("", root_sha)])
    while queue:
        prefix, sha = queue.popleft()
        if stats["requests"] >= max_requests:
            stats["request_limit_hit"] = stats["incomplete"] = True
            break
        stats["requests"] += 1
        level = fetch_level(sha)
        if level.get("truncated"):
            stats["truncated_dirs"] += 1
            stats["incomplete"] = True
        for e in level.get("tree", []):
            path = f"{prefix}{e['path']}"
            if e.get("type") == "blob":
                entries.append({**e, "path": path})
            elif e.get("type") == "tree":
                if dir_excluded(path):
                    stats["pruned_dirs"] += 1

                    if dir_excluded_reason is not None and dir_excluded_reason(path) == "gitignored":
                        stats["pruned_gitignored"] += 1
                else:
                    queue.append((path + "/", e["sha"]))
    return entries, stats
