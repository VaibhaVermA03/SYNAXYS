"""Pure-stdlib security helpers (HMAC verification, redaction, fingerprints)."""
import hashlib
import hmac
import re

_SIG_PREFIX = "sha256="


def verify_github_signature(secret: str, raw_body: bytes, header: str | None) -> bool:
    """Verify X-Hub-Signature-256 over the exact raw body, constant-time."""
    if not secret or not header or not header.startswith(_SIG_PREFIX):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len(_SIG_PREFIX):])


_SECRET_PATTERNS = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{50,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9_\-./+=]{12,}"),
]


def contains_secret(text: str) -> bool:
    return any(p.search(text) for p in _SECRET_PATTERNS)


def secret_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) character spans of anything that looks like a credential, over the WHOLE text
    (so multi-line private keys and secrets inside very long lines are covered)."""
    return [m.span() for p in _SECRET_PATTERNS for m in p.finditer(text)]


def redact_secrets(text: str) -> str:
    for p in _SECRET_PATTERNS:
        text = p.sub("[REDACTED]", text)
    return text


def finding_fingerprint(repo_id: int, pr_number: int, path: str, start: int | None,
                        end: int | None, category: str, title: str) -> str:
    """Stable ID used to prevent duplicate findings/comments across retries."""
    raw = "|".join(map(str, (repo_id, pr_number, path, start, end, category,
                             " ".join(title.lower().split()))))
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
