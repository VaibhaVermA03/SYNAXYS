"""All persistent entities. Credentials are stored only as Fernet ciphertext (*_enc)."""
from datetime import datetime

from sqlalchemy import (JSON, BigInteger, Boolean, Float, ForeignKey, Index, Integer,
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
    __table_args__ = (Index("ix_jobs_status_run_after", "status", "run_after"),)
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
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|dismissed|published
    review: Mapped[CodeReview] = relationship(back_populates="findings")
    comment: Mapped["ReviewComment | None"] = relationship(back_populates="finding", uselist=False, cascade="all, delete-orphan")


class ReviewComment(Base, TimestampMixin):
    __tablename__ = "review_comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("review_findings.id", ondelete="CASCADE"), unique=True)
    body: Mapped[str] = mapped_column(Text)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    state: Mapped[str] = mapped_column(String(20), default="draft")  # draft|approved|published|failed|cancelled
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    github_comment_id: Mapped[int | None] = mapped_column(BigInteger)
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


class IndexedFile(Base):
    """Per-file index state; blob_sha comparison makes re-indexing incremental."""
    __tablename__ = "indexed_files"
    __table_args__ = (UniqueConstraint("repository_id", "path"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(1000))
    blob_sha: Mapped[str] = mapped_column(String(64))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    indexed_at: Mapped[datetime] = mapped_column(DT, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(64))
    meta: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DT, default=utcnow)
