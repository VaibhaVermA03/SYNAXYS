from pydantic import BaseModel


class RecentReview(BaseModel):
    id: int
    status: str
    repository: str
    pr_number: int
    pr_title: str
    findings: int
    created_at: str
    duration_ms: int | None = None
    is_demo: bool


class DayCount(BaseModel):
    date: str
    count: int


class DashboardOut(BaseModel):
    total_repositories: int
    connected_repositories: int
    open_pull_requests: int
    reviews_completed: int
    reviews_by_status: dict[str, int]
    findings_by_severity: dict[str, int]
    avg_review_duration_ms: int | None
    indexing_by_status: dict[str, int]
    recent_reviews: list[RecentReview]
    has_demo_data: bool
    reviews_by_day: list[DayCount] = []
    published_comments: int = 0
    failed_reviews: int = 0
