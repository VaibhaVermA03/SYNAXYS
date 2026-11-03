from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.pull_requests import ReviewBrief


class CommentOut(BaseModel):
    id: int
    state: str
    body: str
    edited: bool


class FindingOut(BaseModel):
    id: int
    category: str
    severity: str
    title: str
    explanation: str
    evidence: str
    path: str
    start_line: int | None
    end_line: int | None
    remediation: str | None
    patch: str | None
    confidence: float
    confidence_label: str
    inline_possible: bool
    status: str
    comment: CommentOut | None = None


class ReviewListItem(ReviewBrief):
    repository: str
    pr_id: int
    pr_number: int
    pr_title: str


class ReviewPage(BaseModel):
    items: list[ReviewListItem]
    total: int
    page: int
    page_size: int


class ReviewDetail(ReviewListItem):
    summary: str | None
    model: str | None
    ai_generated: bool = True
    by_category: dict[str, int]
    findings_list: list[FindingOut]
    require_approval: bool
    auto_publish: bool
    can_retry: bool
    can_manage: bool = False
    approved_comments: int = 0
    publishable: bool = False
    publish_blocker: str | None = None


class CommentPatch(BaseModel):
    body: str | None = Field(None, max_length=4000)
    state: Literal["draft", "cancelled"] | None = None


class ApproveIn(BaseModel):
    comment_ids: list[int] | None = Field(None, max_length=500)


class ApproveOut(BaseModel):
    approved: int


class PublishOut(BaseModel):
    posted: int
    skipped_existing: int
    failed: int
    github_review_id: int | None = None


class AttemptOut(BaseModel):
    id: int
    comment_id: int | None
    status: str
    http_status: int | None
    error: str | None
    actor: str | None
    created_at: str
