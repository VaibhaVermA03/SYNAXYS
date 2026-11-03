"""Retry / rate-limit / pagination logic for GitHub calls, independent of the HTTP library.

`send` is a zero-arg callable returning an object with .status_code, .headers, .json().
"""
import random
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from app.core.exceptions import RateLimited, UpstreamError


class GitHubAPIError(UpstreamError):
    def __init__(self, status: int, message: str = "GitHub API request failed"):
        super().__init__(message, code="github_api_error")
        self.status = status


@dataclass
class Result:
    status: int
    headers: dict
    body: Any


_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')


def parse_next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    m = _NEXT.search(link_header)
    return m.group(1) if m else None


def _h(headers, name):
    for k, v in headers.items():
        if k.lower() == name:
            return v
    return None


def rate_limit_wait(status: int, headers: dict, now: float) -> float | None:
    """Seconds to wait if this is a rate-limit response, else None."""
    if status not in (403, 429):
        return None
    ra = _h(headers, "retry-after")  # secondary limits
    if ra and str(ra).isdigit():
        return float(ra)
    if _h(headers, "x-ratelimit-remaining") == "0":
        reset = _h(headers, "x-ratelimit-reset")
        if reset and str(reset).isdigit():
            return max(0.0, float(reset) - now)
    return None


def execute_with_retry(send: Callable[[], Any], *, max_attempts: int = 4, max_wait: float = 30.0,
                       retry_exceptions: tuple = (), sleep=time.sleep, now=time.time,
                       rand=random.random) -> Result:
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = send()
        except retry_exceptions as exc:  # network/timeout
            last_exc = exc
            if attempt == max_attempts:
                raise GitHubAPIError(0, "GitHub is unreachable") from exc
            sleep(min(max_wait, 2 ** attempt * 0.5 * (0.5 + rand())))
            continue
        status, headers = resp.status_code, dict(resp.headers)
        if 200 <= status < 300:
            body = None if status == 204 else resp.json()
            return Result(status, headers, body)
        wait = rate_limit_wait(status, headers, now())
        if wait is not None:
            if wait > max_wait or attempt == max_attempts:
                raise RateLimited("GitHub rate limit reached; retry later", code="github_rate_limited")
            sleep(wait + rand())
            continue
        if status >= 500 and attempt < max_attempts:  # transient
            sleep(min(max_wait, 2 ** attempt * 0.5 * (0.5 + rand())))
            continue
        raise GitHubAPIError(status, f"GitHub returned HTTP {status}")
    raise GitHubAPIError(0, "GitHub request failed") from last_exc  # pragma: no cover
