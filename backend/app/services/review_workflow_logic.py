"""Pure rules for the Phase 2 review workflow (no third-party imports; unit tested).

* finding dismissal carry-over: a finding the team dismissed must not come back as a new open finding on the next review
* GitHub comment deletion: prove the comment on GitHub is OURS and belongs to THIS repository/pull request before deleting
* search -> pull request navigation: only links stored from GitHub's own payloads, never constructed
"""
import re
from urllib.parse import urlparse

DISMISS_REASONS = ("false_positive", "not_applicable", "will_fix_later", "accepted_risk", "other")
_MARKER = re.compile(r"<!--\s*synaxys:fp=([0-9a-f]{8,64})\s*-->")


def _norm(s: str | None) -> str:
    return " ".join((s or "").lower().split())


def loose_key(path: str, category: str, title: str, evidence: str) -> tuple[str, str, str, str]:
    """Identifies 'the same problem in the same code' even when line numbers moved: the evidence is a literal quote of the code."""
    return (path, category, _norm(title), _norm(evidence))


def build_dismissed_index(rows) -> dict:
    """rows: iterable of objects/dicts with fingerprint, path, category, title, evidence (+ whatever the caller wants back)."""
    idx: dict = {}
    for r in rows:
        get = (lambda k: r[k]) if isinstance(r, dict) else (lambda k: getattr(r, k))
        idx.setdefault(("fp", get("fingerprint")), r)
        idx.setdefault(("loose", loose_key(get("path"), get("category"), get("title"), get("evidence"))), r)
    return idx


def match_dismissed(f: dict, index: dict):
    """f: new finding dict. Returns the earlier dismissed row it corresponds to, or None."""
    hit = index.get(("fp", f["fingerprint"]))
    if hit is not None:
        return hit
    return index.get(("loose", loose_key(f["path"], f["category"], f["title"], f["evidence"])))


# ---- review cancellation ------------------------------------------------------------------------
def cancel_blocker(*, review_status: str, is_demo: bool) -> str | None:
    """None when a cancel may be attempted. The queue decides atomically whether it is still possible."""
    if is_demo:
        return "demo_readonly"
    if review_status == "queued":
        return None
    if review_status == "processing":
        return "already_running"
    if review_status == "cancelled":
        return "already_cancelled"
    return "not_cancellable"  # completed / failed: nothing is waiting in the queue (completed may already be on GitHub)


CANCEL_MESSAGES = {
    "demo_readonly": "Demo reviews are sample data and cannot be cancelled.",
    "already_running": "This review has already started and can no longer be cancelled.",
    "already_cancelled": "This review is already cancelled.",
    "not_cancellable": "Only reviews that are still waiting in the queue can be cancelled.",
    "not_queued": "This review was picked up by a worker a moment ago and can no longer be cancelled.",
    "no_job": "No waiting job was found for this review; it cannot be cancelled.",
}


# ---- GitHub comment deletion --------------------------------------------------------------------
def marker_fingerprints(body: str | None) -> set[str]:
    return set(_MARKER.findall(body or ""))


def verify_comment_ownership(gc: dict, *, full_name: str, number: int, fingerprint: str, app_slug: str) -> str | None:
    """None = safe to delete, else a reason code. Every check must pass:
    * the comment's pull_request_url points at THIS repository and THIS pull request number
    * its body carries OUR hidden marker for THIS finding's fingerprint
    * when the GitHub App slug is configured, it was authored by that app's bot account"""
    pr_url = str(gc.get("pull_request_url") or "")
    path = urlparse(pr_url).path.lower().rstrip("/")
    if path != f"/repos/{full_name.lower()}/pulls/{int(number)}":
        return "wrong_pull_request"
    if fingerprint not in marker_fingerprints(gc.get("body")):
        return "not_our_comment"
    if app_slug:
        login = str((gc.get("user") or {}).get("login") or "").lower()
        if login != f"{app_slug.lower()}[bot]":
            return "not_our_comment"
    return None


DELETE_BLOCKERS = {
    "demo_readonly": "Demo comments are sample data and were never posted to GitHub.",
    "not_published": "Only comments that were published to GitHub can be deleted from GitHub.",
    "already_deleted": "This comment was already deleted.",
    "wrong_pull_request": "The comment on GitHub does not belong to this pull request. Nothing was deleted.",
    "not_our_comment": "The comment on GitHub was not created by SYNAXYS for this finding. Nothing was deleted.",
    "still_exists": "GitHub reported success but the comment still exists. Please check on GitHub.",
}


# ---- search -> pull request ---------------------------------------------------------------------
def safe_github_pr_url(url: str | None) -> str | None:
    """Only a stored https://github.com/<owner>/<repo>/pull/<n> URL is ever linked."""
    if not url:
        return None
    u = urlparse(url)
    if u.scheme != "https" or u.netloc.lower() != "github.com" or not re.fullmatch(r"/[\w.\-]+/[\w.\-]+/pull/\d+/?", u.path):
        return None
    return url


def pick_related_pr(hit_branch: str | None, hit_commit: str | None, prs: list[dict]) -> dict | None:
    """prs: PRs of the hit's repository: {id, number, title, state, head_branch, head_sha, html_url, updated}.
    Priority: a PR whose head commit IS the indexed commit, then a PR whose head branch IS the searched branch
    (open before closed, newest first). Returns {..., match} or None. Never guesses by file path or similarity."""
    def usable(p):
        return safe_github_pr_url(p.get("html_url")) is not None
    if hit_commit:
        for p in sorted(prs, key=lambda p: -p["number"]):
            if p.get("head_sha") == hit_commit and usable(p):
                return {**p, "match": "commit"}
    if hit_branch:
        cands = [p for p in prs if p.get("head_branch") == hit_branch and usable(p)]
        cands.sort(key=lambda p: (p.get("state") != "open", -(p.get("updated") or 0), -p["number"]))
        if cands:
            return {**cands[0], "match": "branch"}
    return None
