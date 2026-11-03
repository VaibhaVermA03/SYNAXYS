"""Stdlib-only primitives: session tokens, CSRF, PKCE (RFC 7636), signed short-lived state."""
import base64
import hashlib
import hmac
import json
import secrets
import time


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64url(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Only this hash is stored; a DB leak does not yield usable session cookies."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_csrf_secret() -> str:
    return secrets.token_hex(16)


def csrf_token(app_secret: str, csrf_secret: str) -> str:
    return hmac.new(app_secret.encode(), f"csrf:{csrf_secret}".encode(), hashlib.sha256).hexdigest()


def verify_csrf(app_secret: str, csrf_secret: str, supplied: str | None) -> bool:
    return bool(supplied) and hmac.compare_digest(csrf_token(app_secret, csrf_secret), supplied)


def pkce_challenge(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode()).digest())


def new_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)  # 86 chars, within RFC 43..128
    return verifier, pkce_challenge(verifier)


def sign_payload(secret: str, purpose: str, payload: dict, ttl_seconds: int, now: float | None = None) -> str:
    body = dict(payload, p=purpose, exp=int((now or time.time()) + ttl_seconds))
    b = _b64url(json.dumps(body, separators=(",", ":")).encode())
    sig = _b64url(hmac.new(secret.encode(), b.encode(), hashlib.sha256).digest())
    return f"{b}.{sig}"


def verify_payload(secret: str, purpose: str, token: str | None, now: float | None = None) -> dict | None:
    if not token or token.count(".") != 1:
        return None
    b, sig = token.split(".")
    expected = _b64url(hmac.new(secret.encode(), b.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        data = json.loads(_unb64url(b))
    except (ValueError, json.JSONDecodeError):
        return None
    if data.get("p") != purpose or data.get("exp", 0) < (now or time.time()):
        return None
    return data
