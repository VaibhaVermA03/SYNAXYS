"""Pure rules for the admin job screen (no third-party imports; unit tested)."""
VALID_STATUSES = ("queued", "processing", "succeeded", "failed", "cancelled")
VALID_KINDS = ("review", "publish", "index", "index_delete", "index_branch_delete", "account_export")
RETRYABLE_STATUSES = ("failed",)
PAYLOAD_ALLOWLIST = ("review_id", "repository_id", "branch", "commit", "indexing_job_id")
MAX_PAGE_SIZE = 100


def safe_payload(payload) -> dict:
    """Only ids and branch/commit names are ever shown; anything else in a job payload is dropped (it could hold
    code, tokens or user text). Strings are truncated."""
    out: dict = {}
    if not isinstance(payload, dict):
        return out
    for k in PAYLOAD_ALLOWLIST:
        v = payload.get(k)
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            out[k] = v
        elif isinstance(v, str):
            out[k] = v[:12] if k == "commit" else v[:100]
    return out


def can_retry(status: str) -> bool:
    return status in RETRYABLE_STATUSES


def clamp_page(page: int, page_size: int) -> tuple[int, int]:
    return max(1, int(page)), min(MAX_PAGE_SIZE, max(1, int(page_size)))
