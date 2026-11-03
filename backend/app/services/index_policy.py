"""What may be indexed, how vectors are named, and what changed since the last index. Pure."""
import hashlib

from app.core.security import secret_spans
from app.services.chunking import Chunk
from app.services.diff_service import is_probably_binary
from app.services.review_context import path_exclusion_reason

NAMESPACE_PREFIX = "repo-"


def namespace_for(repo_id: int) -> str:
    """One Pinecone namespace per repository = tenant isolation boundary for every query/delete."""
    return f"{NAMESPACE_PREFIX}{int(repo_id)}"


def path_hash(path: str) -> str:
    return hashlib.sha1(path.encode()).hexdigest()[:16]


def vector_id(path: str, chunk_index: int) -> str:
    return f"{path_hash(path)}#{chunk_index:04d}"


def file_prefix(path: str) -> str:
    return f"{path_hash(path)}#"


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


def plan_index(existing: dict[str, str], tree: list[dict], *, max_bytes: int, max_files: int) -> dict:
    """existing: path -> blob_sha already indexed. tree: GitHub tree entries.
    Returns {to_index, to_delete, unchanged, skipped:{reason: n}, truncated_by_limit}."""
    eligible: dict[str, dict] = {}
    skipped: dict[str, int] = {}
    for e in tree:
        if e.get("type") != "blob":
            continue
        reason = index_exclusion_reason(e["path"], int(e.get("size") or 0), max_bytes)
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
        else:
            eligible[e["path"]] = e
    paths = sorted(eligible)
    limited = len(paths) > max_files
    paths = paths[:max_files]
    keep = set(paths)
    return {
        "to_index": [eligible[p] for p in paths if existing.get(p) != eligible[p]["sha"]],
        "to_delete": sorted(p for p in existing if p not in keep),
        "unchanged": sum(1 for p in paths if existing.get(p) == eligible[p]["sha"]),
        "skipped": skipped, "limited": limited, "eligible": len(paths),
    }
