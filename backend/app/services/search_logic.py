"""Pure helpers for code search results."""
import re
from urllib.parse import quote

from app.services.embedding_service import tokens
from app.services.index_policy import file_prefix  # noqa: F401  (re-exported for callers)

_STOP = {"the", "a", "an", "of", "to", "in", "and", "or", "for", "is", "are", "with", "how", "what", "where", "does", "do", "from", "this", "that"}


def github_blob_url(full_name: str, commit: str | None, path: str, start: int | None, end: int | None) -> str | None:
    if not commit or not re.fullmatch(r"[\w.\-]+/[\w.\-]+", full_name) or ".." in full_name:
        return None
    frag = f"#L{start}-L{end}" if start and end and end != start else f"#L{start}" if start else ""
    return f"https://github.com/{full_name}/blob/{commit}/{quote(path)}{frag}"


def explain_match(query: str, snippet: str, path: str, score: float) -> str:
    """Concise, deterministic relevance note (keyword overlap + similarity band). Not an LLM explanation."""
    q = {t for t in tokens(query) if t not in _STOP and len(t) > 1}
    in_code, in_path = sorted(q & set(tokens(snippet))), sorted(q & set(tokens(path)))
    band = "strong" if score >= 0.6 else "moderate" if score >= 0.4 else "weak"
    parts = [f"{band} semantic similarity ({score:.2f})"]
    if in_code:
        parts.append("code mentions " + ", ".join(in_code[:5]))
    if in_path:
        parts.append("file path matches " + ", ".join(in_path[:3]))
    return "; ".join(parts) + "."


def merge_results(per_repo: list[tuple[dict, list[dict]]], top_k: int) -> list[dict]:
    """per_repo: [(repo_info, matches)] -> best-first merged list with repo info attached."""
    rows = [{**m, "repo": info} for info, matches in per_repo for m in matches]
    rows.sort(key=lambda r: (-r["score"], r["repo"]["full_name"], r["id"]))
    return rows[:top_k]


def build_filter(branch: str | None, language: str | None) -> dict | None:
    f = {}
    if branch:
        f["branch"] = branch
    if language:
        f["language"] = language.lower()
    return f or None
