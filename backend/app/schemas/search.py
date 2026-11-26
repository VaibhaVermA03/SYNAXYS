from typing import Literal

from pydantic import BaseModel, Field


class SearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    repository_id: int | None = None
    branch: str | None = Field(None, max_length=200, pattern=r"^[\w./\-]+$")
    language: str | None = Field(None, max_length=30, pattern=r"^[A-Za-z+#]+$")
    top_k: int = Field(10, ge=1, le=20)


class PullRequestRef(BaseModel):
    """A pull request related to a hit. html_url is the URL GitHub itself reported for the PR (stored from its webhook payload); it is never built by us."""
    id: int  # SYNAXYS pull request id (internal page: /app/pull-requests/<id>)
    number: int
    title: str
    state: str  # open | closed | merged
    html_url: str
    match: Literal["commit", "branch"]  # why it is related: its head commit IS the indexed commit / its head branch IS the searched branch


class SearchHit(BaseModel):
    id: str
    score: float
    repository: str
    repository_id: int
    path: str
    start_line: int | None
    end_line: int | None
    language: str | None
    branch: str | None
    commit: str | None
    snippet: str
    explanation: str
    github_url: str | None
    pull_request: PullRequestRef | None = None


class SearchBranchOut(BaseModel):
    branch: str
    repositories: int  # how many of the caller's searchable repositories have this branch indexed
    is_default_somewhere: bool


class SearchBranchesOut(BaseModel):
    branches: list[SearchBranchOut]


class SearchOut(BaseModel):
    results: list[SearchHit]
    searched_repositories: list[str]
    backend: str
    note: str | None = None
    branch: str | None = None  # the branch that was requested (None = each repository's default branch)


class IndexJobOut(BaseModel):
    id: int
    status: str
    commit: str | None = None
    files_total: int
    files_indexed: int
    chunks_upserted: int
    error: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    branch: str | None = None
    batches: dict[str, int] | None = None  # {pending, done, failed}
    plan: dict | None = None  # counts only: eligible / selected / deferred / skipped reasons / how the tree was listed


class BranchStateOut(BaseModel):
    branch: str
    is_default: bool
    status: str  # queued|indexing|indexed|partial|failed|missing
    last_indexed_commit: str | None = None
    last_indexed_at: str | None = None
    error: str | None = None
    files_indexed: int = 0
    files_eligible: int = 0
    files_deferred: int = 0
    failed_batches: int = 0
    tree_incomplete: bool = False


class IndexBranchIn(BaseModel):
    branch: str | None = Field(None, max_length=200, pattern=r"^[\w./\-]+$")  # None = the default branch


class GitHubBranchesOut(BaseModel):
    default_branch: str
    branches: list[str]
    indexed: list[str]
    max_extra_branches: int


class IndexStatusOut(BaseModel):
    branch: str | None = None  # the branch this status/job describes (default branch unless asked)
    branches: list[BranchStateOut] = []
    status: str
    available: bool
    unavailable_reason: str | None = None
    backend: str
    last_indexed_at: str | None = None
    last_indexed_commit: str | None = None
    error: str | None = None
    indexed_files: int
    job: IndexJobOut | None = None
