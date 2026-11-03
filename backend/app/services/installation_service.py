"""Repository synchronization scoped to what GitHub says THIS user can access."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import GitHubInstallation, Repository, RepositoryAccess, ReviewConfiguration, User
from app.services.github_service import GitHubClient


def sync_user_repositories(db: Session, gh: GitHubClient, user: User, user_token: str) -> dict:
    inst_count = repo_count = removed = 0
    for inst in gh.list_user_installations(user_token):
        inst_id = int(inst["id"])
        row = db.scalar(select(GitHubInstallation).where(GitHubInstallation.installation_id == inst_id))
        acct = inst.get("account") or {}
        if row is None:
            row = GitHubInstallation(installation_id=inst_id, account_login=acct.get("login", "unknown"),
                                     account_type=acct.get("type", "User"), permissions=inst.get("permissions"))
            db.add(row)
        row.account_login = acct.get("login", row.account_login)
        row.suspended_at = utcnow() if inst.get("suspended_at") else None
        row.deleted_at = None
        if acct.get("login") == user.login and row.owner_user_id is None:
            row.owner_user_id = user.id
        db.flush()
        inst_count += 1

        seen_repo_ids: set[int] = set()
        for r in gh.list_user_installation_repos(user_token, inst_id):
            repo = db.scalar(select(Repository).where(Repository.github_repo_id == int(r["id"])))
            if repo is None:
                repo = Repository(installation_id=row.id, github_repo_id=int(r["id"]), full_name=r["full_name"])
                repo.config = ReviewConfiguration()
                db.add(repo)
            repo.installation_id = row.id
            repo.full_name, repo.default_branch = r["full_name"], r.get("default_branch") or "main"
            repo.is_private, repo.language, repo.html_url = bool(r.get("private")), r.get("language"), r.get("html_url")
            db.flush()
            seen_repo_ids.add(repo.id)
            role = "owner" if (r.get("permissions") or {}).get("admin") else "member"
            acc = db.scalar(select(RepositoryAccess).where(RepositoryAccess.user_id == user.id, RepositoryAccess.repository_id == repo.id))
            if acc is None:
                db.add(RepositoryAccess(user_id=user.id, repository_id=repo.id, role=role))
            else:
                acc.role = role
            repo_count += 1

        # Revocation: drop access to repos in this installation that GitHub no longer grants this user.
        stale = db.scalars(
            select(RepositoryAccess).join(Repository, Repository.id == RepositoryAccess.repository_id)
            .where(RepositoryAccess.user_id == user.id, Repository.installation_id == row.id,
                   RepositoryAccess.repository_id.not_in(seen_repo_ids or {-1}))).all()
        for a in stale:
            db.delete(a)
            removed += 1
    db.commit()
    return {"installations": inst_count, "repositories": repo_count, "access_removed": removed}
