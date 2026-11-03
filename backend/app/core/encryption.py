"""Authenticated encryption (Fernet) for stored credentials. Keys live in env, not DB.

ENCRYPTION_KEY may hold several comma-separated keys: first encrypts, all decrypt,
which enables rotation (prepend new key, re-encrypt, then drop the old one).
Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from app.core.exceptions import NotConfigured


def _fernet(key_spec: str):
    from cryptography.fernet import Fernet, MultiFernet
    keys = [k.strip() for k in key_spec.split(",") if k.strip()]
    if not keys:
        raise NotConfigured("ENCRYPTION_KEY is not configured", code="encryption_not_configured")
    return MultiFernet([Fernet(k.encode()) for k in keys])


def encrypt_secret(plaintext: str, key_spec: str) -> str:
    return _fernet(key_spec).encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str, key_spec: str) -> str:
    return _fernet(key_spec).decrypt(token.encode()).decode()
