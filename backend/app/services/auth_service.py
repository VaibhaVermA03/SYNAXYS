"""User upsert, server-side sessions. Token encryption via core.encryption."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth_tokens import hash_token, new_csrf_secret, new_session_token
from app.core.config import Settings
from app.core.encryption import encrypt_secret
from app.db.base import utcnow
from app.models import OAuthIdentity, User, UserSession


def aware(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; treat them as UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def upsert_user_from_github(db: Session, s: Settings, gh_user: dict, access_token: str, scopes: str = "") -> User:
    gid = int(gh_user["id"])
    user = db.scalar(select(User).where(User.github_id == gid))
    if user is None:
        user = User(github_id=gid, login=gh_user["login"])
        db.add(user)
    user.login, user.name = gh_user["login"], gh_user.get("name")
    user.email, user.avatar_url = gh_user.get("email"), gh_user.get("avatar_url")
    db.flush()
    ident = db.scalar(select(OAuthIdentity).where(OAuthIdentity.provider == "github", OAuthIdentity.provider_user_id == str(gid)))
    if ident is None:
        ident = OAuthIdentity(user_id=user.id, provider="github", provider_user_id=str(gid))
        db.add(ident)
    ident.access_token_enc = encrypt_secret(access_token, s.encryption_key)
    ident.scopes = scopes
    db.commit()
    return user


def create_session(db: Session, s: Settings, user: User, user_agent: str | None) -> str:
    raw = new_session_token()
    db.add(UserSession(token_hash=hash_token(raw), csrf_secret=new_csrf_secret(), user_id=user.id,
                       expires_at=utcnow() + timedelta(hours=s.session_ttl_hours), user_agent=(user_agent or "")[:300]))
    db.commit()
    return raw


def resolve_session(db: Session, raw_token: str | None) -> tuple[User, UserSession] | None:
    if not raw_token:
        return None
    sess = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(raw_token)))
    if sess is None or sess.revoked_at is not None or aware(sess.expires_at) <= utcnow():
        return None
    user = db.get(User, sess.user_id)
    if user is None or not user.is_active:
        return None
    return user, sess


def revoke_session(db: Session, raw_token: str | None) -> None:
    if not raw_token:
        return
    sess = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(raw_token)))
    if sess and sess.revoked_at is None:
        sess.revoked_at = utcnow()
        db.commit()
