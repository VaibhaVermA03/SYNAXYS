"""Lazily created, process-wide Redis client for the rate limiter. Returns None when Redis is not configured or the
`redis` package is missing; callers (DistributedLimiter) treat None as 'unavailable' and apply the failure mode."""
import logging
import threading

log = logging.getLogger("synaxys.redis")
_lock = threading.Lock()
_client = None
_client_url = None
_import_error_logged = False


def get_redis(settings):
    """Never raises; never logs the URL (it may contain a password)."""
    global _client, _client_url, _import_error_logged
    url = (settings.redis_url or "").strip()
    if not url:
        return None
    with _lock:
        if _client is not None and _client_url == url:
            return _client
        try:
            import redis
        except ImportError:
            if not _import_error_logged:
                log.error("REDIS_URL is set but the 'redis' package is not installed; rate limiting falls back (mode=%s)", settings.rate_limit_redis_failure)
                _import_error_logged = True
            return None
        t = settings.rate_limit_redis_timeout_seconds
        _client = redis.Redis.from_url(url, socket_timeout=t, socket_connect_timeout=t, health_check_interval=30, decode_responses=False)
        _client_url = url
        return _client


def reset_redis_client() -> None:
    """Tests only."""
    global _client, _client_url
    with _lock:
        _client = _client_url = None
