from typing import Literal

from pydantic import BaseModel, Field


class WorkspaceOut(BaseModel):
    id: int
    name: str
    role: Literal["owner", "admin", "member"]  # the caller's role
    invite_policy: str
    members: int
    repositories: int


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class WorkspacePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    invite_policy: Literal["owner", "admin"] | None = None


class WorkspaceDelete(BaseModel):
    confirm_name: str = Field(max_length=100)


class MemberOut(BaseModel):
    user_id: int
    login: str
    name: str | None = None
    avatar_url: str | None = None
    role: str
    joined_at: str


class RolePatch(BaseModel):
    role: Literal["admin", "member"]


class TransferIn(BaseModel):
    user_id: int


class InvitationCreate(BaseModel):
    login: str = Field(min_length=1, max_length=60)
    role: Literal["admin", "member"] = "member"


class InvitationOut(BaseModel):
    id: int
    login: str
    role: str
    status: str  # pending | accepted | revoked | expired
    expires_at: str
    created_at: str


class InvitationCreated(InvitationOut):
    token: str  # shown ONCE; stored only as a hash. Share the link /app/invitations/<token> with exactly this GitHub user.


class MyInvitationOut(InvitationOut):
    workspace_id: int
    workspace_name: str


class AcceptIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class AuditEntryOut(BaseModel):
    id: int
    action: str
    actor: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    created_at: str


class NotificationOut(BaseModel):
    id: int
    kind: str
    title: str
    body: str | None = None
    link: str | None = None
    workspace_id: int | None = None
    read: bool
    created_at: str


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    total: int
    unread: int
    page: int
    page_size: int


class ExportOut(BaseModel):
    id: int
    status: str  # pending | ready | failed
    size_bytes: int
    created_at: str
    expires_at: str
    downloaded_at: str | None = None
    error: str | None = None


class DeleteAccountIn(BaseModel):
    confirm_login: str = Field(max_length=100)
