"""Typed settings, validated at startup. Backend secrets never use VITE_ variables."""
from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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

    @field_validator("database_url")
    @classmethod
    def _normalise_db_url(cls, v: str) -> str:
        return normalize_database_url(v)

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
