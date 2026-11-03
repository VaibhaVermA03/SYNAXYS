"""Pure rules for publishing review comments to GitHub (no I/O).

* Every posted comment carries a hidden marker with the finding fingerprint, so retries, crashes
  between "GitHub accepted" and "DB committed", and webhook re-deliveries can never double-post.
* The review event is ALWAYS "COMMENT": SYNAXYS never approves or requests changes automatically.
"""
import re

EVENT = "COMMENT"
MAX_BODY = 60_000  # GitHub limit is 65,536
_MARKER = re.compile(r"<!--\s*synaxys:fp=([0-9a-f]{8,64})\s*-->")


def marker(fingerprint: str) -> str:
    return f"<!-- synaxys:fp={fingerprint} -->"


def with_marker(body: str, fingerprint: str) -> str:
    return body.rstrip()[: MAX_BODY - 80] + "\n\n" + marker(fingerprint)


def existing_markers(github_comments: list[dict]) -> set[str]:
    found: set[str] = set()
    for c in github_comments or []:
        found.update(_MARKER.findall(str(c.get("body") or "")))
    return found


def inline_payload(path: str, start: int | None, end: int | None, body: str) -> dict:
    """GitHub review-comment object for the NEW side of the diff (multi-line when start < end)."""
    d = {"path": path, "line": end, "side": "RIGHT", "body": body}
    if start is not None and start < end:
        d.update(start_line=start, start_side="RIGHT")
    return d


def plan(items: list[dict], existing: set[str]) -> tuple[list[dict], list[dict]]:
    """items: [{fingerprint, ...}] -> (to_post, already_on_github)."""
    to_post, dup, seen = [], [], set()
    for it in items:
        fp = it["fingerprint"]
        (dup if fp in existing or fp in seen else to_post).append(it)
        seen.add(fp)
    return to_post, dup


# (code, http_status, message)
BLOCKERS = {
    "demo_readonly": (400, "Demo reviews are sample data and can never be published."),
    "review_not_completed": (400, "Only completed reviews can be published."),
    "repository_not_connected": (400, "Connect this repository before publishing."),
    "pr_not_open": (400, "The pull request is no longer open."),
    "review_stale": (409, "The pull request changed after this review. Run a new review before publishing; line numbers may no longer match."),
    "github_app_not_configured": (503, "GitHub App is not configured; cannot publish."),
}


def publish_blocker(*, review_status: str, is_demo: bool, repo_enabled: bool, pr_state: str, pr_head: str, review_head: str, app_configured: bool) -> str | None:
    if is_demo:
        return "demo_readonly"
    if review_status != "completed":
        return "review_not_completed"
    if not repo_enabled:
        return "repository_not_connected"
    if pr_state != "open":
        return "pr_not_open"
    if pr_head != review_head:
        return "review_stale"
    if not app_configured:
        return "github_app_not_configured"
    return None


TRANSITIONS = {  # manual comment state changes: from -> allowed targets
    "draft": {"cancelled"}, "approved": {"draft", "cancelled"}, "failed": {"draft", "cancelled"}, "cancelled": {"draft"},
}


def can_transition(frm: str, to: str) -> bool:
    return to in TRANSITIONS.get(frm, set())
