"""Pure retry/timeout policy for the durable job queue."""
import random
from datetime import datetime, timedelta, timezone

from app.core.exceptions import BadRequest, Forbidden, NotConfigured, NotFound, RateLimited
from app.core.security import redact_secrets
from app.services.github_http import GitHubAPIError


def backoff_seconds(attempt: int, base: float = 15.0, cap: float = 900.0, rand=random.random) -> float:
    """Exponential backoff with jitter in [50%, 100%] of the exponential value."""
    exp = min(cap, base * (2 ** max(0, attempt - 1)))
    return exp * (0.5 + 0.5 * rand())


def is_stale(locked_at: datetime | None, timeout_seconds: int, now: datetime) -> bool:
    if locked_at is None:
        return True
    if locked_at.tzinfo is None:
        locked_at = locked_at.replace(tzinfo=timezone.utc)
    return locked_at + timedelta(seconds=timeout_seconds) < now


def sanitize_error(exc_or_msg, limit: int = 500) -> str:
    msg = exc_or_msg if isinstance(exc_or_msg, str) else f"{type(exc_or_msg).__name__}: {exc_or_msg}"
    return redact_secrets(" ".join(msg.split()))[:limit]


def is_retriable(exc: Exception) -> bool:
    """Permanent errors fail fast; transient ones are retried up to max_attempts."""
    if isinstance(exc, RateLimited):
        return True
    if isinstance(exc, GitHubAPIError):
        return exc.status == 0 or exc.status >= 500 or exc.status in (408, 429)
    if isinstance(exc, (NotConfigured, BadRequest, NotFound, Forbidden)):
        return False
    return True
