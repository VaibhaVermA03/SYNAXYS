"""Typed settings, validated at startup. Backend secrets never use VITE_ variables."""
from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.admin import parse_admin_ids
from app.core.db_url import normalize_database_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    app_secret_key: str = "dev-only-change-me"
    database_url: str = "sqlite:///./synaxys_dev.sqlite3"
    frontend_url: str = "http://localhost:5173"
    backend_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:5173"
    log_level: str = "INFO"

    github_client_id: str = ""
    github_client_secret: str = ""
    github_redirect_uri: str = "http://localhost:8000/api/v1/auth/github/callback"
    github_app_id: str = ""
    github_app_slug: str = ""
    github_app_private_key: str = ""  # PEM, or use *_PATH
    github_app_private_key_path: str = ""
    github_webhook_secret: str = ""

    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536  # MUST equal the Pinecone index dimension

    pinecone_api_key: str = ""
    pinecone_index_name: str = "synaxys-code"
    vector_backend: Literal["pinecone", "memory"] = "pinecone"  # "memory" = explicit, process-local dev/test adapter (never production)
    index_max_file_bytes: int = 200_000
    index_max_files: int = 3000
    index_chunk_chars: int = 1500
    index_embed_batch: int = 64
    # Phase 3: scalable partial indexing
    index_batch_files: int = 25  # files per persisted batch (the unit of progress and of retry)
    index_batch_bytes: int = 2_000_000  # total blob bytes per batch
    index_max_chunks_per_run: int = 20_000  # embedding budget of ONE job run; when reached the job stops as 'partial' and resumes on request
    index_max_branches: int = 5  # extra indexed branches per repository besides the default branch (bounds Pinecone usage)
    index_max_tree_requests: int = 400  # GitHub tree requests when a repository's recursive tree is truncated
    index_max_continuations: int = 200  # time-slice continuations of one job
    index_respect_gitignore: bool = True  # honour the repository's root .gitignore
    search_rate_limit_per_minute: int = 30
    context_retrieval_enabled: bool = True
    context_min_score: float = 0.35

    encryption_key: str = ""  # comma-separated Fernet keys; first encrypts, all decrypt (rotation)

    session_ttl_hours: int = 12
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    max_request_bytes: int = 2_000_000
    demo_login_enabled: bool = False  # opt-in developer/e2e helper (API only, no UI); always ignored in production
    trust_proxy_headers: bool = False  # true only behind a trusted reverse proxy
    github_oauth_scope: str = "read:user"
    auth_rate_limit_per_minute: int = 10
    review_max_files: int = 50
    review_max_patch_bytes: int = 200_000
    worker_concurrency: int = 2
    job_max_attempts: int = 4
    review_use_mock_llm: bool = False  # explicit opt-in: labelled deterministic mock, never a silent fallback
    review_min_confidence: float = 0.5
    review_max_findings: int = 30
    review_batch_chars: int = 24_000
    review_total_chars: int = 120_000
    review_max_batches: int = 6
    openai_timeout_seconds: int = 60
    job_default_timeout_seconds: int = 600
    worker_poll_interval_seconds: float = 2.0
    worker_heartbeat_path: str = "/tmp/synaxys_worker.heartbeat"
    worker_shutdown_grace_seconds: int = 30


    # ---- Phase 1: distributed rate limiting (Redis) ----
    redis_url: str = ""  # empty = per-process in-memory limiter (single instance only). redis:// or rediss://
    rate_limit_redis_failure: Literal["memory", "closed", "open"] = "memory"  # what to do while Redis is unreachable
    rate_limit_redis_timeout_seconds: float = 0.25
    rate_limit_redis_retry_seconds: int = 15  # circuit breaker: skip Redis for this long after a failure
    rate_limit_key_prefix: str = "synaxys:rl"
    global_rate_limit_per_minute: int = 300  # per client IP, all API routes except health and the GitHub webhook
    user_rate_limit_per_minute: int = 240  # per authenticated user, authenticated routes
    trusted_proxy_hops: int = 0  # 0 = legacy (first X-Forwarded-For entry); N>0 = N-th entry from the right. See docs/PHASE1_OPERATIONS.md

    # ---- Phase 1: platform administrators ----
    admin_github_ids: str = ""  # comma-separated numeric GitHub user IDs (NOT logins)

    # ---- Phase 1: Sentry (all optional; empty DSN = disabled) ----
    sentry_dsn: str = ""
    sentry_environment: str = ""  # defaults to APP_ENV
    sentry_release: str = ""
    sentry_traces_sample_rate: float = 0.0  # performance tracing is off by default

    export_ttl_hours: int = 24  # account data exports expire (and are deleted by the cleanup job) after this long

    # ---- Phase 1: automatic cleanup / retention (days; 0 disables that rule where noted) ----
    cleanup_enabled: bool = True
    cleanup_interval_minutes: int = 60
    cleanup_batch_size: int = 500
    cleanup_max_batches: int = 20  # per rule per run; the rest is picked up by the next run
    retention_sessions_days: int = 7  # after a session expired / was revoked
    retention_webhook_days: int = 30  # minimum 7: also the window in which a replayed delivery GUID is recognised
    retention_jobs_done_days: int = 14  # succeeded / cancelled jobs
    retention_jobs_failed_days: int = 60
    retention_indexing_jobs_days: int = 30  # the latest job per repository is always kept
    retention_audit_days: int = 365  # 0 = keep forever
    retention_security_audit_days: int = 730  # auth.* / admin.* / credential events; 0 = keep forever
    retention_invitations_days: int = 30  # answered/expired workspace invitations (pending ones expire after 7 days by themselves)
    retention_notifications_days: int = 90  # READ notifications
    retention_notifications_max_days: int = 365  # any notification, read or not

    @field_validator("database_url")
    @classmethod
    def _normalise_db_url(cls, v: str) -> str:
        return normalize_database_url(v)

    @field_validator("admin_github_ids")
    @classmethod
    def _check_admin_ids(cls, v: str) -> str:
        parse_admin_ids(v)  # raises ValueError on anything that is not a positive integer
        return v

    @property
    def admin_github_id_set(self) -> frozenset[int]:
        return parse_admin_ids(self.admin_github_ids)

    @property
    def redis_configured(self) -> bool:
        return bool(self.redis_url.strip())

    @property
    def sentry_configured(self) -> bool:
        return bool(self.sentry_dsn.strip())

    @model_validator(mode="after")
    def _retention_guards(self):
        if self.retention_webhook_days < 7:
            raise ValueError("RETENTION_WEBHOOK_DAYS must be >= 7 (replay protection window)")
        if self.cleanup_batch_size < 1 or self.cleanup_max_batches < 1 or self.cleanup_interval_minutes < 1:
            raise ValueError("CLEANUP_BATCH_SIZE, CLEANUP_MAX_BATCHES and CLEANUP_INTERVAL_MINUTES must be >= 1")
        if self.trusted_proxy_hops < 0:
            raise ValueError("TRUSTED_PROXY_HOPS must be >= 0")
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def github_oauth_configured(self) -> bool:
        return bool(self.github_client_id and self.github_client_secret)

    @property
    def github_app_configured(self) -> bool:
        return bool(self.github_app_id and (self.github_app_private_key or self.github_app_private_key_path))

    @property
    def demo_login_available(self) -> bool:
        return self.demo_login_enabled and not self.is_production

    @property
    def openai_configured(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def pinecone_configured(self) -> bool:
        return bool(self.pinecone_api_key)

    @model_validator(mode="after")
    def _production_guards(self):
        if self.is_production:
            problems = []
            if self.app_secret_key in ("", "dev-only-change-me") or len(self.app_secret_key) < 32:
                problems.append("APP_SECRET_KEY must be >=32 random chars")
            if not self.encryption_key:
                problems.append("ENCRYPTION_KEY is required")
            if not self.github_webhook_secret:
                problems.append("GITHUB_WEBHOOK_SECRET is required")
            if not self.cookie_secure:
                problems.append("COOKIE_SECURE must be true")
            if self.database_url.startswith("sqlite"):
                problems.append("DATABASE_URL must be PostgreSQL in production")
            if self.review_use_mock_llm:
                problems.append("REVIEW_USE_MOCK_LLM must be false in production (the mock is not AI)")
            if self.vector_backend == "memory":
                problems.append("VECTOR_BACKEND=memory is for local demos only")
            if problems:
                raise ValueError("Invalid production config: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
