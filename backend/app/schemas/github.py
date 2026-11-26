from typing import Annotated, Literal

from pydantic import BaseModel, Field


class RepositoryOut(BaseModel):
    id: int
    full_name: str
    default_branch: str
    is_private: bool
    language: str | None = None
    html_url: str | None = None
    is_enabled: bool
    is_demo: bool
    role: str
    index_status: str
    last_indexed_at: str | None = None
    index_error: str | None = None


class RepositoryPage(BaseModel):
    items: list[RepositoryOut]
    total: int
    page: int
    page_size: int


class InstallationOut(BaseModel):
    id: int
    account_login: str
    account_type: str
    is_demo: bool


class InstallationsOut(BaseModel):
    items: list[InstallationOut]
    install_url: str | None = None


class SyncOut(BaseModel):
    installations: int
    repositories: int
    access_removed: int


class ConnectIn(BaseModel):
    workspace_id: int | None = None  # defaults to the active workspace, or the user's only workspace


class ReviewConfigOut(BaseModel):
    require_approval: bool
    auto_publish: bool
    allowed_actions: list[str]
    max_files: int
    max_patch_bytes: int
    index_enabled: bool
    index_include_globs: list[str] = []
    index_exclude_globs: list[str] = []
    index_max_files: int | None = None


class ReviewConfigPatch(BaseModel):
    require_approval: bool | None = None
    auto_publish: bool | None = None
    allowed_actions: list[Literal["opened", "synchronize", "reopened"]] | None = None
    max_files: int | None = Field(None, ge=1, le=200)
    max_patch_bytes: int | None = Field(None, ge=10_000, le=1_000_000)
    index_enabled: bool | None = None
    index_include_globs: list[Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[\w.*?/\-\[\]@+]+$")]] | None = Field(None, max_length=50)  # gitignore-style globs; empty = no restriction
    index_exclude_globs: list[Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[\w.*?/\-\[\]@+]+$")]] | None = Field(None, max_length=50)
    index_max_files: int | None = Field(None, ge=1, le=100_000)  # capped by INDEX_MAX_FILES; null = use the global limit
