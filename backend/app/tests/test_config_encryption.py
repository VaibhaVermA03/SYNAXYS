"""Requires installed deps (pydantic-settings, cryptography). Run: pytest"""
import pytest


def test_production_requires_secrets():
    from app.core.config import Settings
    with pytest.raises(ValueError):
        Settings(app_env="production", _env_file=None)


def test_encrypt_roundtrip_and_rotation():
    from cryptography.fernet import Fernet
    from app.core.encryption import decrypt_secret, encrypt_secret
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    token = encrypt_secret("gho_secret", old)
    assert "gho_secret" not in token
    assert decrypt_secret(token, f"{new},{old}") == "gho_secret"  # rotation: old key still decrypts
    with pytest.raises(Exception):
        decrypt_secret(token, new)


def test_migration_and_seed_on_sqlite(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/t.sqlite3")
    from alembic import command
    from alembic.config import Config
    command.upgrade(Config("alembic.ini"), "head")
    from app.db.seed import seed
    seed(); seed()  # idempotent


def test_key_rotation_script_reencrypts_only_old_tokens(tmp_path, monkeypatch):
    import sys
    from cryptography.fernet import Fernet
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/t.sqlite3")
    monkeypatch.setenv("ENCRYPTION_KEY", f"{new},{old}")

    for m in [m for m in sys.modules if m.startswith("app.") and not m.startswith("app.tests")]:
        del sys.modules[m]
    from app.core.config import get_settings; get_settings.cache_clear()
    from app.db.base import Base
    from app.db.session import SessionLocal, engine
    from app.models import OAuthIdentity, User
    
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        u = User(github_id=1, login="a"); db.add(u); db.flush()
        db.add_all([OAuthIdentity(user_id=u.id, provider_user_id="1", access_token_enc=Fernet(old.encode()).encrypt(b"gho_old").decode()),
                    OAuthIdentity(user_id=u.id, provider_user_id="2", access_token_enc=Fernet(new.encode()).encrypt(b"gho_new").decode())]); db.commit()
    from app.scripts.rotate_keys import main
    assert main(dry_run=True) == 0
    with SessionLocal() as db:   # dry run changes nothing
        assert Fernet(old.encode()).decrypt(db.get(OAuthIdentity, 1).access_token_enc.encode()) == b"gho_old"
    assert main() == 0
    with SessionLocal() as db:
        assert [Fernet(new.encode()).decrypt(i.access_token_enc.encode()) for i in db.scalars(__import__("sqlalchemy").select(OAuthIdentity)).all()] == [b"gho_old", b"gho_new"]


def test_production_rejects_demo_adapters():
    from app.core.config import Settings
    base = dict(app_env="production", app_secret_key="x" * 40, encryption_key="k", github_webhook_secret="w", cookie_secure=True,
                database_url="postgresql://u:p@h/d", _env_file=None)
    assert Settings(**base).database_url == "postgresql+psycopg://u:p@h/d"              # normalised
    for bad in ({"review_use_mock_llm": True}, {"vector_backend": "memory"}):
        with pytest.raises(ValueError):
            Settings(**base, **bad)


def test_demo_login_is_opt_in_and_never_available_in_production(monkeypatch):
    from app.core.config import Settings
    monkeypatch.delenv("DEMO_LOGIN_ENABLED", raising=False)
    assert Settings(_env_file=None).demo_login_available is False                    # off unless explicitly enabled
    assert Settings(_env_file=None, demo_login_enabled=True).demo_login_available is True
    prod = dict(app_env="production", app_secret_key="x" * 40, encryption_key="k", github_webhook_secret="w", cookie_secure=True, database_url="postgresql://u:p@h/d", _env_file=None)
    assert Settings(**prod, demo_login_enabled=True).demo_login_available is False   # the production switch wins
