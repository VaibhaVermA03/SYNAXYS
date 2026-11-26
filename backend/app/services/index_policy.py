"""What may be indexed, how vectors are named, and what changed since the last index. Pure."""
import hashlib

import posixpath

from app.core.security import secret_spans
from app.services.chunking import Chunk
from app.services.diff_service import is_probably_binary
from app.services.review_context import glob_match, path_exclusion_reason

NAMESPACE_PREFIX = "repo-"


def namespace_for(repo_id: int) -> str:
    """One Pinecone namespace per repository = tenant isolation boundary for every query/delete."""
    return f"{NAMESPACE_PREFIX}{int(repo_id)}"


def path_hash(path: str) -> str:
    return hashlib.sha1(path.encode()).hexdigest()[:16]


def branch_tag(branch: str) -> str:
    return hashlib.sha1(branch.encode()).hexdigest()[:8]


def branch_prefix(branch: str) -> str:
    """Every vector of one branch starts with this, so a whole branch can be listed and removed by prefix."""
    return f"{branch_tag(branch)}:"


def vector_id(path: str, chunk_index: int, branch: str | None = None) -> str:
    """branch=None is the LEGACY (pre-branch-aware) id `<pathhash>#<n>`; current ids are `<branchtag>:<pathhash>#<n>`, so the same file
    on two branches never collides. The legacy form can never be a prefix of the new one (`#` vs `:` after different hash lengths)."""
    return f"{branch_prefix(branch) if branch is not None else ''}{path_hash(path)}#{chunk_index:04d}"


def file_prefix(path: str, branch: str | None = None) -> str:
    return f"{branch_prefix(branch) if branch is not None else ''}{path_hash(path)}#"


def index_exclusion_reason(path: str, size: int, max_bytes: int) -> str | None:
    if is_probably_binary(path):
        return "binary"
    reason = path_exclusion_reason(path)
    if reason:
        return reason
    return "too_large" if size > max_bytes else None


def decode_text(raw: bytes) -> str | None:
    """None for binary/non-UTF-8 content."""
    if b"\x00" in raw[:8000]:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def secret_line_numbers(text: str) -> set[int]:
    """1-based line numbers touched by any credential-looking span (multi-line keys included)."""
    spans = secret_spans(text)
    if not spans:
        return set()
    starts, pos = [], 0
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        starts.append(pos)
        pos += len(line) + 1
    import bisect
    out: set[int] = set()
    for a, b in spans:
        out.update(range(bisect.bisect_right(starts, a) , bisect.bisect_right(starts, max(a, b - 1)) + 1))
    return out


def drop_secret_chunks(chunks: list[Chunk], text: str) -> tuple[list[Chunk], int]:
    """Credentials are never embedded or stored. Detection runs on the full file BEFORE chunk boundaries
    matter, so a secret split across chunk pieces (e.g. a very long line) cannot slip through."""
    bad = secret_line_numbers(text)
    if not bad:
        return list(chunks), 0
    kept = [c for c in chunks if not any(n in bad for n in range(c.start_line, c.end_line + 1))]
    return kept, len(chunks) - len(kept)


_CODE = {".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".go", ".rs", ".java", ".kt", ".kts", ".rb", ".php", ".cs", ".c", ".h", ".cc", ".cpp", ".hpp", ".swift",
         ".scala", ".sh", ".bash", ".sql", ".lua", ".dart", ".vue", ".svelte", ".ex", ".exs", ".clj", ".hs", ".ml", ".r", ".jl", ".pl", ".m"}
_CONFIG = {".yml", ".yaml", ".toml", ".json", ".xml", ".ini", ".cfg", ".html", ".css", ".scss", ".less", ".tf", ".gradle", ".proto", ".graphql"}
_DOCS = {".md", ".rst", ".txt", ".adoc"}


def priority(path: str, size: int) -> tuple:
    """Sort key used when a repository has more eligible files than the limit: source code first (tests after production code), then
    configuration, then documentation, then everything else; shallower and smaller files first; ties by path (deterministic)."""
    ext = posixpath.splitext(path.lower())[1]
    low = "/" + path.lower()
    is_test = any(x in low for x in ("/test/", "/tests/", "/__tests__/", "/spec/")) or posixpath.basename(low).startswith("test_") or ".test." in low or ".spec." in low or low.endswith("_test.go")
    cls = (1 if is_test else 0) if ext in _CODE else 2 if ext in _CONFIG else 3 if ext in _DOCS else 4
    return (cls, path.count("/"), size // 8192, path)


def plan_index(existing: dict[str, str], tree: list[dict], *, max_bytes: int, max_files: int, ignore=None, include_globs=(), exclude_globs=(),
               reindex_paths=frozenset(), allow_delete: bool = True) -> dict:
    """existing: path -> blob_sha already indexed (for ONE branch). tree: GitHub tree entries (full paths).
    ignore: GitIgnore-like object (.ignored(path)); include_globs: when non-empty only matching paths are indexed; exclude_globs always win.
    reindex_paths: indexed paths whose vectors use an old id scheme (re-embedded even if unchanged).
    allow_delete=False for an INCOMPLETE tree listing: 'not listed' must never be read as 'deleted'.
    Returns {to_index, to_delete, unchanged, skipped:{reason:n}, limited, eligible, selected, deferred}."""
    eligible: dict[str, dict] = {}
    skipped: dict[str, int] = {}

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for e in tree:
        if e.get("type") != "blob":
            continue
        path = e["path"]
        reason = index_exclusion_reason(path, int(e.get("size") or 0), max_bytes)
        if reason is None and ignore is not None and ignore.ignored(path):
            reason = "gitignored"
        if reason is None and any(glob_match(g, path) for g in exclude_globs):
            reason = "excluded_by_config"
        if reason is None and include_globs and not any(glob_match(g, path) for g in include_globs):
            reason = "not_included"
        if reason:
            skip(reason)
        else:
            eligible[path] = e
    ranked = sorted(eligible, key=lambda p: priority(p, int(eligible[p].get("size") or 0)))
    limited = len(ranked) > max_files
    paths = ranked[:max_files]
    keep = set(paths)
    changed = [p for p in paths if existing.get(p) != eligible[p]["sha"] or p in reindex_paths]
    return {
        "to_index": [eligible[p] for p in sorted(changed, key=lambda p: priority(p, int(eligible[p].get("size") or 0)))],
        "to_delete": sorted(p for p in existing if p not in keep) if allow_delete else [],
        "unchanged": len(paths) - len(changed),
        "skipped": skipped, "limited": limited, "eligible": len(eligible), "selected": len(paths), "deferred": len(eligible) - len(paths),
    }


def make_batches(to_index: list[dict], to_delete: list[str], *, batch_files: int, batch_bytes: int) -> list[dict]:
    """Deletions first (cheap, frees vectors), then index batches bounded by file count AND total bytes. A file larger than batch_bytes gets a batch of its own."""
    out: list[dict] = []
    for i in range(0, len(to_delete), max(1, batch_files * 4)):
        out.append({"kind": "delete", "items": [{"path": p} for p in to_delete[i:i + max(1, batch_files * 4)]]})
    cur: list[dict] = []
    size = 0
    for e in to_index:
        sz = int(e.get("size") or 0)
        if cur and (len(cur) >= batch_files or size + sz > batch_bytes):
            out.append({"kind": "index", "items": cur})
            cur, size = [], 0
        cur.append({"path": e["path"], "sha": e["sha"], "size": sz})
        size += sz
    if cur:
        out.append({"kind": "index", "items": cur})
    return out


def dir_excluded_factory(ignore=None, exclude_globs=()):
    """Directory filter for the tree walker: vendored/build directories, .gitignore'd directories, and config-excluded directories are never listed."""
    def excluded(dirpath: str) -> bool:
        if path_exclusion_reason(dirpath + "/x") == "vendored_or_build":
            return True
        if ignore is not None and ignore.ignored(dirpath, is_dir=True):
            return True
        return any(glob_match(g, dirpath + "/x") and glob_match(g, dirpath + "/y") for g in exclude_globs)
    return excluded
