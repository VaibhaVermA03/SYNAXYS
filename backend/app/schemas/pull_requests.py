from typing import Literal

from pydantic import BaseModel


class ReviewBrief(BaseModel):
    id: int
    status: str
    trigger: str
    findings: int
    by_severity: dict[str, int]
    created_at: str
    finished_at: str | None = None
    duration_ms: int | None = None
    error: str | None = None
    is_demo: bool = False
    head_sha: str


class PullRequestOut(BaseModel):
    id: int
    repository_id: int
    repository: str
    number: int
    title: str
    author: str
    state: Literal["open", "closed", "merged"]
    base_branch: str
    head_branch: str
    html_url: str | None = None
    updated_at: str
    is_demo: bool
    review: ReviewBrief | None = None


class PullRequestPage(BaseModel):
    items: list[PullRequestOut]
    total: int
    page: int
    page_size: int


class PullRequestDetail(PullRequestOut):
    head_sha: str
    repo_enabled: bool
    can_request_review: bool
    reviews: list[ReviewBrief]


class DiffHunk(BaseModel):
    header: str
    lines: list[dict]


class DiffFile(BaseModel):
    path: str
    previous_path: str | None = None
    status: str
    additions: int
    deletions: int
    skipped_reason: str | None = None
    hunks: list[DiffHunk]


class DiffOut(BaseModel):
    files: list[DiffFile]
    omitted_files: int
    head_sha: str
    is_demo: bool
