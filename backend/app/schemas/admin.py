from pydantic import BaseModel


class AdminJobOut(BaseModel):
    id: int
    kind: str
    status: str
    attempts: int
    max_attempts: int
    created_at: str
    run_after: str | None = None
    finished_at: str | None = None
    error: str | None = None  # already redacted + truncated when it was stored; never a stack trace
    repository_id: int | None = None
    repository: str | None = None
    pull_request_number: int | None = None
    workspace: str | None = None  # reserved for the workspaces phase
    can_retry: bool


class AdminJobDetail(AdminJobOut):
    timeout_seconds: int
    locked_at: str | None = None
    locked_by: str | None = None
    payload: dict
    review_status: str | None = None


class AdminJobPage(BaseModel):
    items: list[AdminJobOut]
    total: int
    page: int
    page_size: int


class AdminJobStats(BaseModel):
    by_status: dict[str, int]
    failed_by_kind: dict[str, int]
    failed_last_24h: int
    queued_oldest_age_seconds: int | None = None
    stale_processing: int
    total: int
