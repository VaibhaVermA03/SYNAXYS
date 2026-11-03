from pydantic import BaseModel


class IntegrationItem(BaseModel):
    key: str
    label: str
    configured: bool
    detail: str
    env: list[str]


class IntegrationsOut(BaseModel):
    items: list[IntegrationItem]
    environment: str
    webhook_url: str
    oauth_callback_url: str
    install_url: str | None
    demo_login: bool
    mock_llm: bool
    vector_backend: str
    github_token_stored: bool


class AuditOut(BaseModel):
    id: int
    action: str
    target_type: str | None
    target_id: str | None
    created_at: str
