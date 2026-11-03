"""Installations, repository listing (scoped by RepositoryAccess), sync, connect/disconnect."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_github_client, rate_limit, settings_dep
from app.core.config import Settings
from app.core.encryption import decrypt_secret
from app.core.exceptions import BadRequest, Conflict
from app.db.session import get_db
from app.models import (AuditLog, GitHubInstallation, OAuthIdentity, Repository, RepositoryAccess,
                        ReviewConfiguration, User)
from app.repositories.access import get_repo_for_user
from app.schemas.github import (InstallationOut, InstallationsOut, RepositoryOut, RepositoryPage, ReviewConfigOut, ReviewConfigPatch, SyncOut)
from app.services import job_queue
from app.services.github_http import GitHubAPIError
from app.services.github_service import GitHubClient
from app.services.installation_service import sync_user_repositories

router = APIRouter(prefix="/github", tags=["github"])
limit_sync = rate_limit("sync", 6)


def _repo_out(repo: Repository, role: str) -> RepositoryOut:
    return RepositoryOut(id=repo.id, full_name=repo.full_name, default_branch=repo.default_branch, is_private=repo.is_private,
                         language=repo.language, html_url=repo.html_url, is_enabled=repo.is_enabled, is_demo=repo.is_demo,
                         role=role, index_status=repo.index_status,
                         last_indexed_at=repo.last_indexed_at.isoformat() if repo.last_indexed_at else None,
                         index_error=repo.index_error)


@router.get("/installations", response_model=InstallationsOut)
def installations(db: Session = Depends(get_db), user: User = Depends(current_user), s: Settings = Depends(settings_dep)):
    rows = db.scalars(
        select(GitHubInstallation).join(Repository, Repository.installation_id == GitHubInstallation.id)
        .join(RepositoryAccess, RepositoryAccess.repository_id == Repository.id)
        .where(RepositoryAccess.user_id == user.id).distinct()).all()
    url = f"https://github.com/apps/{s.github_app_slug}/installations/new" if s.github_app_slug else None
    return InstallationsOut(items=[InstallationOut(id=r.id, account_login=r.account_login, account_type=r.account_type, is_demo=r.is_demo) for r in rows],
                            install_url=url)


@router.get("/repositories", response_model=RepositoryPage)
def list_repositories(q: str | None = None, connected: bool | None = None, page: int = Query(1, ge=1),
                      page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(current_user)):
    base = (select(Repository, RepositoryAccess.role).join(RepositoryAccess, RepositoryAccess.repository_id == Repository.id)
            .where(RepositoryAccess.user_id == user.id))
    if q:
        base = base.where(Repository.full_name.ilike(f"%{q.replace('%', '').replace('_', '')}%"))
    if connected is not None:
        base = base.where(Repository.is_enabled == connected)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(base.order_by(Repository.full_name).limit(page_size).offset((page - 1) * page_size)).all()
    return RepositoryPage(items=[_repo_out(r, role) for r, role in rows], total=total, page=page, page_size=page_size)


@router.post("/repositories/sync", response_model=SyncOut, dependencies=[Depends(limit_sync)])
def sync(db: Session = Depends(get_db), user: User = Depends(current_user), s: Settings = Depends(settings_dep),
         gh: GitHubClient = Depends(get_github_client)):
    ident = db.scalar(select(OAuthIdentity).where(OAuthIdentity.user_id == user.id, OAuthIdentity.provider == "github"))
    if ident is None or not ident.access_token_enc:
        raise Conflict("GitHub credentials are not available. Sign in with GitHub again.", code="github_reauth_required")
    try:
        token = decrypt_secret(ident.access_token_enc, s.encryption_key)
        result = sync_user_repositories(db, gh, user, token)
    except GitHubAPIError as e:
        if e.status in (401, 403):  # expired/revoked user token
            raise Conflict("GitHub rejected the stored credentials. Sign in with GitHub again.", code="github_reauth_required")
        raise
    db.add(AuditLog(user_id=user.id, action="github.sync", meta=result))
    db.commit()
    return SyncOut(**result)


@router.post("/repositories/{repository_id}/connect", response_model=RepositoryOut)
def connect(repository_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    repo = get_repo_for_user(db, user, repository_id, require_owner=True)  # GitHub admin required
    if repo.config is None:
        repo.config = ReviewConfiguration()
    repo.is_enabled = True
    db.add(AuditLog(user_id=user.id, action="repository.connect", target_type="repository", target_id=str(repo.id)))
    db.commit()
    return _repo_out(repo, "owner")


@router.delete("/repositories/{repository_id}/disconnect", response_model=RepositoryOut)
def disconnect(repository_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    repo = get_repo_for_user(db, user, repository_id, require_owner=True)
    repo.is_enabled = False
    # Vector cleanup is performed by the worker; durable, and re-queued on every disconnect.
    job_queue.enqueue_or_requeue(db, "index_delete", {"repository_id": repo.id}, f"index_delete:{repo.id}")
    repo.index_status = "not_indexed"
    db.add(AuditLog(user_id=user.id, action="repository.disconnect", target_type="repository", target_id=str(repo.id)))
    db.commit()
    return _repo_out(repo, "owner")


@router.delete("/credentials", status_code=204)
def revoke_stored_credentials(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Deletes the stored (encrypted) GitHub user token. Re-login is required to sync again."""
    ident = db.scalar(select(OAuthIdentity).where(OAuthIdentity.user_id == user.id, OAuthIdentity.provider == "github"))
    if ident:
        ident.access_token_enc = None
    db.add(AuditLog(user_id=user.id, action="github.credentials_revoked"))
    db.commit()


def _cfg_out(repo: Repository) -> ReviewConfigOut:
    c = repo.config or ReviewConfiguration()
    return ReviewConfigOut(require_approval=c.require_approval if c.require_approval is not None else True, auto_publish=bool(c.auto_publish),
                           allowed_actions=list(c.allowed_actions or ["opened", "synchronize", "reopened"]), max_files=c.max_files or 50,
                           max_patch_bytes=c.max_patch_bytes or 200_000, index_enabled=True if c.index_enabled is None else c.index_enabled)


@router.get("/repositories/{repository_id}/config", response_model=ReviewConfigOut)
def get_review_config(repository_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _cfg_out(get_repo_for_user(db, user, repository_id))


@router.patch("/repositories/{repository_id}/config", response_model=ReviewConfigOut)
def update_review_config(repository_id: int, body: ReviewConfigPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    repo = get_repo_for_user(db, user, repository_id, require_owner=True)  # only repository admins may change publishing policy
    if repo.config is None:
        repo.config = ReviewConfiguration()
    cfg, data = repo.config, body.model_dump(exclude_unset=True)
    if data.get("auto_publish") is True and data.get("require_approval") is True:
        raise BadRequest("auto_publish and require_approval cannot both be enabled.", code="conflicting_policy")
    if data.get("auto_publish") is True:
        data["require_approval"] = False
    if data.get("require_approval") is True:
        data["auto_publish"] = False
    before = {"auto_publish": cfg.auto_publish, "require_approval": cfg.require_approval}
    for k, v in data.items():
        setattr(cfg, k, v)
    db.add(AuditLog(user_id=user.id, action="repository.config_update", target_type="repository", target_id=str(repo.id),
                    meta={"changed": sorted(data), "before": before, "after": {"auto_publish": cfg.auto_publish, "require_approval": cfg.require_approval}}))
    db.commit()
    return _cfg_out(repo)
