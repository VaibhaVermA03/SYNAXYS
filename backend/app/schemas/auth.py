from pydantic import BaseModel


class UserOut(BaseModel):
    id: int
    login: str
    name: str | None = None
    avatar_url: str | None = None


class IntegrationStatus(BaseModel):
    github_oauth: bool
    github_app: bool
    webhook_secret: bool
    openai: bool
    pinecone: bool
    demo_mode: bool
    demo_login: bool


class MeOut(BaseModel):
    user: UserOut
    csrf_token: str
    integrations: IntegrationStatus
