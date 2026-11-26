from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.pull_requests import ReviewBrief


class CommentOut(BaseModel):
    id: int
    state: str  # GitHub comment lifecycle: draft|approved|publishing|published|failed|cancelled|deleted
    body: str
    edited: bool
    github_deleted_at: str | None = None


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
    status: str  # finding lifecycle: open|dismissed|published (independent of comment.state and review status)
    dismissed_at: str | None = None
    dismissed_by: str | None = None
    dismiss_reason: str | None = None
    dismiss_note: str | None = None
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
    dismissed_count: int = 0
    can_cancel: bool = False


class CommentPatch(BaseModel):
    body: str | None = Field(None, max_length=4000)
    state: Literal["draft", "cancelled"] | None = None


class DismissIn(BaseModel):
    reason: Literal["false_positive", "not_applicable", "will_fix_later", "accepted_risk", "other"] | None = None
    note: str | None = Field(None, max_length=300)


class FindingStateOut(BaseModel):
    id: int
    status: str
    dismissed_at: str | None = None
    dismiss_reason: str | None = None
    dismiss_note: str | None = None
    comment: CommentOut | None = None


class CancelOut(BaseModel):
    status: str
    cancelled_jobs: int


class DeleteCommentOut(BaseModel):
    outcome: Literal["deleted", "already_deleted"]
    state: str


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
    action: str | None = None  # 'delete' for GitHub comment deletions; absent for publishing attempts
