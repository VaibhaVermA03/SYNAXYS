from pydantic import BaseModel, Field


class SearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    repository_id: int | None = None
    branch: str | None = Field(None, max_length=200, pattern=r"^[\w./\-]+$")
    language: str | None = Field(None, max_length=30, pattern=r"^[A-Za-z+#]+$")
    top_k: int = Field(10, ge=1, le=20)


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


class SearchOut(BaseModel):
    results: list[SearchHit]
    searched_repositories: list[str]
    backend: str
    note: str | None = None


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


class IndexStatusOut(BaseModel):
    status: str
    available: bool
    unavailable_reason: str | None = None
    backend: str
    last_indexed_at: str | None = None
    last_indexed_commit: str | None = None
    error: str | None = None
    indexed_files: int
    job: IndexJobOut | None = None
