"""All persistent entities. Credentials are stored only as Fernet ciphertext (*_enc)."""
from datetime import datetime

from sqlalchemy import (JSON, BigInteger, Boolean, Float, ForeignKey, Index, Integer, LargeBinary,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UTCDateTime,  utcnow

DT = UTCDateTime()


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    login: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class OAuthIdentity(Base, TimestampMixin):
    __tablename__ = "oauth_identities"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(30), default="github")
    provider_user_id: Mapped[str] = mapped_column(String(64))
    access_token_enc: Mapped[str | None] = mapped_column(Text)  # encrypted; never returned to clients
    scopes: Mapped[str | None] = mapped_column(String(500))


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (Index("ix_user_sessions_expires_at", "expires_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # SHA-256 of cookie value
    csrf_secret: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DT, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DT)
    revoked_at: Mapped[datetime | None] = mapped_column(DT)
    user_agent: Mapped[str | None] = mapped_column(String(300))


class GitHubInstallation(Base, TimestampMixin):
    __tablename__ = "github_installations"
    id: Mapped[int] = mapped_column(primary_key=True)
    installation_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    account_login: Mapped[str] = mapped_column(String(100))
    account_type: Mapped[str] = mapped_column(String(20), default="User")
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    permissions: Mapped[dict | None] = mapped_column(JSON)
    suspended_at: Mapped[datetime | None] = mapped_column(DT)
    deleted_at: Mapped[datetime | None] = mapped_column(DT)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class Repository(Base, TimestampMixin):
    __tablename__ = "repositories"
    id: Mapped[int] = mapped_column(primary_key=True)
    installation_id: Mapped[int] = mapped_column(ForeignKey("github_installations.id", ondelete="CASCADE"), index=True)
    github_repo_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    full_name: Mapped[str] = mapped_column(String(200), index=True)
    default_branch: Mapped[str] = mapped_column(String(100), default="main")
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    language: Mapped[str | None] = mapped_column(String(50))
    html_url: Mapped[str | None] = mapped_column(String(500))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)  # reviewing on/off
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="SET NULL"), index=True)  # NULL = only visible to the GitHub users who can see it (connect it into a workspace)
    index_status: Mapped[str] = mapped_column(String(20), default="not_indexed")
    last_indexed_at: Mapped[datetime | None] = mapped_column(DT)
    last_indexed_commit: Mapped[str | None] = mapped_column(String(64))
    index_error: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped["ReviewConfiguration | None"] = relationship(back_populates="repository", uselist=False, cascade="all, delete-orphan")


class RepositoryAccess(Base, TimestampMixin):
    """Who may see/manage a repository. Every query is scoped through this table."""
    __tablename__ = "repository_access"
    __table_args__ = (UniqueConstraint("user_id", "repository_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")  # owner | member


class ReviewConfiguration(Base, TimestampMixin):
    __tablename__ = "review_configurations"
    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), unique=True)
    require_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_publish: Mapped[bool] = mapped_column(Boolean, default=False)  # only owners may enable
    allowed_actions: Mapped[list] = mapped_column(JSON, default=lambda: ["opened", "synchronize", "reopened"])
    max_files: Mapped[int] = mapped_column(Integer, default=50)
    max_patch_bytes: Mapped[int] = mapped_column(Integer, default=200_000)
    index_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    index_include_globs: Mapped[list] = mapped_column(JSON, default=list)  # when non-empty ONLY matching paths are indexed (gitignore-style globs)
    index_exclude_globs: Mapped[list] = mapped_column(JSON, default=list)  # always win over include
    index_max_files: Mapped[int | None] = mapped_column(Integer)  # per-repository cap (never above INDEX_MAX_FILES); None = global default
    repository: Mapped[Repository] = relationship(back_populates="config")


class ReviewRule(Base, TimestampMixin):
    __tablename__ = "review_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    repository_id: Mapped[int | None] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500), default="")
    instruction: Mapped[str] = mapped_column(Text)  # untrusted config; wrapped before LLM use
    severity: Mapped[str] = mapped_column(String(20), default="medium")
    file_patterns: Mapped[list] = mapped_column(JSON, default=list)
    languages: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class PullRequest(Base, TimestampMixin):
    __tablename__ = "pull_requests"
    __table_args__ = (UniqueConstraint("repository_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(500))
    author_login: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(10), default="open")  # open | closed
    merged: Mapped[bool] = mapped_column(Boolean, default=False)
    base_branch: Mapped[str] = mapped_column(String(200))
    head_branch: Mapped[str] = mapped_column(String(200))
    head_sha: Mapped[str] = mapped_column(String(64))
    html_url: Mapped[str | None] = mapped_column(String(500))
    github_updated_at: Mapped[datetime | None] = mapped_column(DT)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    demo_patches: Mapped[dict | None] = mapped_column(JSON)  # demo only: {path: patch}


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (Index("ix_webhook_deliveries_received_at", "received_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[str] = mapped_column(String(64), unique=True)  # idempotency key
    event: Mapped[str] = mapped_column(String(60))
    action: Mapped[str | None] = mapped_column(String(60))
    installation_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default="received")  # received|queued|ignored|failed
    detail: Mapped[str | None] = mapped_column(String(300))  # sanitized
    received_at: Mapped[datetime] = mapped_column(DT, default=utcnow)


class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    __table_args__ = (Index("ix_jobs_status_run_after", "status", "run_after"), Index("ix_jobs_status_finished_at", "status", "finished_at"))
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))  # review | index
    dedup_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|processing|succeeded|failed|cancelled
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=4)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=600)
    run_after: Mapped[datetime] = mapped_column(DT, default=utcnow)
    locked_at: Mapped[datetime | None] = mapped_column(DT)
    locked_by: Mapped[str | None] = mapped_column(String(100))
    last_error: Mapped[str | None] = mapped_column(String(500))  # sanitized
    created_at: Mapped[datetime] = mapped_column(DT, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DT)


class CodeReview(Base, TimestampMixin):
    __tablename__ = "code_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    pull_request_id: Mapped[int] = mapped_column(ForeignKey("pull_requests.id", ondelete="CASCADE"), index=True)
    dedup_key: Mapped[str] = mapped_column(String(200), unique=True)  # e.g. "pr:12:sha:abc:webhook"
    head_sha: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|processing|completed|failed|cancelled
    trigger: Mapped[str] = mapped_column(String(20), default="webhook")
    requested_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    summary: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(80))
    started_at: Mapped[datetime | None] = mapped_column(DT)
    finished_at: Mapped[datetime | None] = mapped_column(DT)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(500))
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DT)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    cancelled_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))  # set when a user cancels a QUEUED review
    cancelled_at: Mapped[datetime | None] = mapped_column(DT)
    findings: Mapped[list["ReviewFinding"]] = relationship(back_populates="review", cascade="all, delete-orphan")


class ReviewFinding(Base, TimestampMixin):
    __tablename__ = "review_findings"
    __table_args__ = (UniqueConstraint("review_id", "fingerprint"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("code_reviews.id", ondelete="CASCADE"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(20))  # bug|security|performance|maintainability|testing
    severity: Mapped[str] = mapped_column(String(20))  # critical|high|medium|low|info
    title: Mapped[str] = mapped_column(String(200))
    explanation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(String(500))
    start_line: Mapped[int | None] = mapped_column(Integer)
    end_line: Mapped[int | None] = mapped_column(Integer)
    remediation: Mapped[str | None] = mapped_column(Text)
    patch: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    inline_possible: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|dismissed|published  (finding lifecycle; NOT the GitHub comment state)
    dismissed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    dismissed_at: Mapped[datetime | None] = mapped_column(DT)
    dismiss_reason: Mapped[str | None] = mapped_column(String(40))  # false_positive|not_applicable|will_fix_later|accepted_risk|other
    dismiss_note: Mapped[str | None] = mapped_column(String(300))
    review: Mapped[CodeReview] = relationship(back_populates="findings")
    comment: Mapped["ReviewComment | None"] = relationship(back_populates="finding", uselist=False, cascade="all, delete-orphan")


class ReviewComment(Base, TimestampMixin):
    __tablename__ = "review_comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("review_findings.id", ondelete="CASCADE"), unique=True)
    body: Mapped[str] = mapped_column(Text)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    state: Mapped[str] = mapped_column(String(20), default="draft")  # draft|approved|published|failed|cancelled|deleted (deleted = removed from GitHub; the row is kept)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    github_comment_id: Mapped[int | None] = mapped_column(BigInteger)
    github_deleted_at: Mapped[datetime | None] = mapped_column(DT)
    github_deleted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    finding: Mapped[ReviewFinding] = relationship(back_populates="comment")


class ReviewPostingAttempt(Base):
    __tablename__ = "review_posting_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("code_reviews.id", ondelete="CASCADE"), index=True)
    comment_id: Mapped[int | None] = mapped_column(ForeignKey("review_comments.id", ondelete="SET NULL"))
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20))  # success|failed|skipped
    http_status: Mapped[int | None] = mapped_column(Integer)
    response_meta: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DT, default=utcnow)


class IndexingJob(Base):
    __tablename__ = "indexing_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    branch: Mapped[str] = mapped_column(String(200))
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    files_total: Mapped[int] = mapped_column(Integer, default=0)
    files_indexed: Mapped[int] = mapped_column(Integer, default=0)
    chunks_upserted: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime | None] = mapped_column(DT)
    finished_at: Mapped[datetime | None] = mapped_column(DT)
    created_at: Mapped[datetime] = mapped_column(DT, default=utcnow)
    plan_summary: Mapped[dict | None] = mapped_column(JSON)  # what was selected/skipped/deferred and how the tree was listed (counts only, no code)
    continuations: Mapped[int] = mapped_column(Integer, default=0)  # time-slice continuations enqueued for this job


class IndexingBatch(Base):
    """One unit of indexing work (a few files). Persisted so progress survives crashes and only failed batches are retried."""
    __tablename__ = "indexing_batches"
    __table_args__ = (UniqueConstraint("job_id", "seq"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("indexing_jobs.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(10))  # index | delete
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | done | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    items: Mapped[list] = mapped_column(JSON, default=list)  # [{path, sha, size}] (index) / [{path}] (delete); after a partial failure only the files still to do
    files_done: Mapped[int] = mapped_column(Integer, default=0)
    chunks: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(500))
    updated_at: Mapped[datetime] = mapped_column(DT, default=utcnow, onupdate=utcnow)


class BranchIndexState(Base):
    """Index state of ONE branch of a repository (a repository can have several indexed branches)."""
    __tablename__ = "branch_index_states"
    __table_args__ = (UniqueConstraint("repository_id", "branch"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    branch: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|indexing|indexed|partial|failed|missing
    last_indexed_commit: Mapped[str | None] = mapped_column(String(64))
    last_indexed_at: Mapped[datetime | None] = mapped_column(DT)
    error: Mapped[str | None] = mapped_column(String(500))
    files_indexed: Mapped[int] = mapped_column(Integer, default=0)
    files_eligible: Mapped[int] = mapped_column(Integer, default=0)
    files_deferred: Mapped[int] = mapped_column(Integer, default=0)  # eligible but over the file limit
    failed_batches: Mapped[int] = mapped_column(Integer, default=0)
    tree_incomplete: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DT, default=utcnow, onupdate=utcnow)


class IndexedFile(Base):
    """Per-file, per-branch index state; blob_sha comparison makes re-indexing incremental.
    (Table renamed from indexed_files in Phase 3 so the unique key could include the branch; migration 0005 copies the old rows.)"""
    __tablename__ = "indexed_branch_files"
    __table_args__ = (UniqueConstraint("repository_id", "branch", "path"), Index("ix_ibf_repo_branch", "repository_id", "branch"))
    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    branch: Mapped[str] = mapped_column(String(200), default="")
    vector_schema: Mapped[int] = mapped_column(Integer, default=2)  # 1 = legacy vector ids (no branch tag), 2 = branch-aware ids
    path: Mapped[str] = mapped_column(String(1000))
    blob_sha: Mapped[str] = mapped_column(String(64))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    indexed_at: Mapped[datetime] = mapped_column(DT, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_created_at", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="SET NULL"), index=True)  # set for workspace-level events
    action: Mapped[str] = mapped_column(String(80), index=True)
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(64))
    meta: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DT, default=utcnow)


class Workspace(Base, TimestampMixin):
    """Tenant boundary (Phase 4). Owns repositories; members get access to ALL of its repositories according to their role.
    A workspace can hold repositories from several GitHub installations (the repository, not the workspace, points at its installation)."""
    __tablename__ = "workspaces"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    invite_policy: Mapped[str] = mapped_column(String(10), default="admin")  # who may invite: owner | admin
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10), default="member")  # owner | admin | member
    invited_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DT, default=utcnow)


class WorkspaceInvitation(Base):
    """Invitation of a GitHub login. Accepting needs BOTH the secret link token and a session of exactly that GitHub user."""
    __tablename__ = "workspace_invitations"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    invited_login: Mapped[str] = mapped_column(String(100), index=True)  # lower-cased GitHub login
    role: Mapped[str] = mapped_column(String(10), default="member")  # admin | member
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # SHA-256 of the link token; the token itself is shown once
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | accepted | revoked | expired
    invited_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    accepted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime] = mapped_column(DT)
    created_at: Mapped[datetime] = mapped_column(DT, default=utcnow)
    responded_at: Mapped[datetime | None] = mapped_column(DT)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("user_id", "dedup_key"), Index("ix_notifications_user_read", "user_id", "read_at"))
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(String(500))
    link: Mapped[str | None] = mapped_column(String(300))  # internal app path only
    dedup_key: Mapped[str] = mapped_column(String(200))  # the same event never notifies the same user twice
    read_at: Mapped[datetime | None] = mapped_column(DT)
    created_at: Mapped[datetime] = mapped_column(DT, default=utcnow)


class DataExport(Base):
    """A user's data export. The archive is stored here (not on disk), is downloadable only by its owner through an authenticated endpoint, and expires."""
    __tablename__ = "data_exports"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | ready | failed
    payload: Mapped[bytes | None] = mapped_column(LargeBinary)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DT, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DT)
    downloaded_at: Mapped[datetime | None] = mapped_column(DT)

