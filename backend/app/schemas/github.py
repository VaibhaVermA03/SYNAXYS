from typing import Literal

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


class ReviewConfigOut(BaseModel):
    require_approval: bool
    auto_publish: bool
    allowed_actions: list[str]
    max_files: int
    max_patch_bytes: int
    index_enabled: bool


class ReviewConfigPatch(BaseModel):
    require_approval: bool | None = None
    auto_publish: bool | None = None
    allowed_actions: list[Literal["opened", "synchronize", "reopened"]] | None = None
    max_files: int | None = Field(None, ge=1, le=200)
    max_patch_bytes: int | None = Field(None, ge=10_000, le=1_000_000)
    index_enabled: bool | None = None
