"""Sentry error tracking with aggressive scrubbing. Everything here is a no-op unless SENTRY_DSN is set and sentry-sdk
is installed. Pure helpers (scrub_event, scrub_breadcrumb, fingerprint_for) have no third-party imports and are unit tested.

What is NEVER sent: request bodies, cookies, Authorization/CSRF/signature headers, query strings (OAuth code/state),
local variables, source-code context lines, user IP/email/name, tokens/keys/passwords (redacted from every string).
Only the numeric user id may be attached. Auto-enabling integrations are off so nothing is captured that is not listed here.
"""
import logging
import re

from app.core.security import redact_secrets

log = logging.getLogger("synaxys.monitoring")
_enabled = False

_SENSITIVE_KEY = re.compile(r"(authorization|cookie|token|secret|password|passwd|api[_-]?key|private[_-]?key|signature|csrf|session|dsn|code|state|body|payload|diff|content|text|snippet)", re.I)
_FRAME_DROP = ("vars", "pre_context", "context_line", "post_context")
_MAX_STR = 500


def _clean_str(v):
    return redact_secrets(" ".join(v.split()))[:_MAX_STR] if isinstance(v, str) else v


def _clean_mapping(d):
    if not isinstance(d, dict):
        return d
    out = {}
    for k, v in d.items():
        if _SENSITIVE_KEY.search(str(k)):
            out[k] = "[Filtered]"
        elif isinstance(v, dict):
            out[k] = _clean_mapping(v)
        elif isinstance(v, str):
            out[k] = _clean_str(v)
        elif isinstance(v, (int, float, bool)) or v is None:
            out[k] = v
        else:
            out[k] = "[Filtered]"
    return out


def _strip_query(url):
    return url.split("?", 1)[0].split("#", 1)[0] if isinstance(url, str) else url


def scrub_breadcrumb(crumb, hint=None):
    if crumb is None:
        return None
    category = crumb.get("category") or ""
    if category == "console":
        return None
    crumb = dict(crumb)
    if "message" in crumb:
        crumb["message"] = _clean_str(crumb["message"])
    data = crumb.get("data") or {}
    keep = {k: (_strip_query(v) if k == "url" else v) for k, v in data.items() if k in ("url", "method", "status_code", "reason")}
    crumb["data"] = keep
    return crumb


def fingerprint_for(exc) -> list[str] | None:
    """Group by what is actionable instead of by message text."""
    name = type(exc).__name__
    status = getattr(exc, "status", None)
    if name == "GitHubAPIError" and status is not None:
        return ["github-api-error", str(status)]
    code = getattr(exc, "code", None)
    if name in ("UpstreamError", "NotConfigured") and isinstance(code, str):
        return [name, code]
    return None


def scrub_event(event, hint=None):
    if event is None:
        return None
    req = event.get("request")
    if isinstance(req, dict):
        event["request"] = {"method": req.get("method"), "url": _strip_query(req.get("url"))}
    user = event.get("user")
    if isinstance(user, dict):
        event["user"] = {"id": str(user["id"])} if user.get("id") is not None else {}
    for v in (event.get("exception") or {}).get("values", []) or []:
        if "value" in v:
            v["value"] = _clean_str(v["value"])
        for fr in (v.get("stacktrace") or {}).get("frames", []) or []:
            for k in _FRAME_DROP:
                fr.pop(k, None)
    for k in ("message", "transaction"):
        if isinstance(event.get(k), str):
            event[k] = _clean_str(event[k])
    le = event.get("logentry")
    if isinstance(le, dict):
        event["logentry"] = {"message": _clean_str(le.get("message") or le.get("formatted") or "")}
    for k in ("extra", "contexts", "tags"):
        if k in event:
            event[k] = _clean_mapping(event[k])
    crumbs = (event.get("breadcrumbs") or {}).get("values") if isinstance(event.get("breadcrumbs"), dict) else None
    if crumbs is not None:
        event["breadcrumbs"]["values"] = [c for c in (scrub_breadcrumb(c) for c in crumbs) if c is not None]
    exc_info = (hint or {}).get("exc_info")
    if exc_info and len(exc_info) > 1 and exc_info[1] is not None:
        fp = fingerprint_for(exc_info[1])
        if fp:
            event["fingerprint"] = fp
    return event


def init_monitoring(settings, component: str) -> bool:
    """component: 'api' | 'worker'. Returns True when Sentry is active."""
    global _enabled
    if not settings.sentry_configured:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.dedupe import DedupeIntegration
        from sentry_sdk.integrations.excepthook import ExcepthookIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.integrations.threading import ThreadingIntegration
    except ImportError:
        log.error("SENTRY_DSN is set but sentry-sdk is not installed; error tracking is disabled")
        return False
    integrations = [DedupeIntegration(), ExcepthookIntegration(), ThreadingIntegration(), LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)]
    if component == "api":
        try:
            from sentry_sdk.integrations.fastapi import FastApiIntegration
            from sentry_sdk.integrations.starlette import StarletteIntegration
            integrations += [StarletteIntegration(), FastApiIntegration()]
        except ImportError:
            log.warning("Sentry FastAPI integration unavailable; only logged errors are reported")
    sentry_sdk.init(
        dsn=settings.sentry_dsn, environment=settings.sentry_environment or settings.app_env, release=settings.sentry_release or None,
        traces_sample_rate=settings.sentry_traces_sample_rate, send_default_pii=False, include_local_variables=False,
        include_source_context=False, max_request_body_size="never", attach_stacktrace=True,
        default_integrations=False, auto_enabling_integrations=False, integrations=integrations,
        before_send=scrub_event, before_send_transaction=scrub_event, before_breadcrumb=scrub_breadcrumb,
    )
    sentry_sdk.set_tag("component", component)
    _enabled = True
    log.info("Sentry enabled (component=%s)", component)
    return True


def capture_exception(exc: BaseException, **tags) -> None:
    """Report a handled exception with tags. Never raises."""
    if not _enabled:
        return
    try:
        import sentry_sdk
        with sentry_sdk.new_scope() as scope:
            for k, v in tags.items():
                scope.set_tag(k, str(v))
            sentry_sdk.capture_exception(exc)
    except Exception:  # noqa: BLE001
        log.debug("failed to report exception to Sentry", exc_info=True)


def capture_job_failure(job_id: int, kind: str, attempts: int, exc: BaseException) -> None:
    """Final (non-retriable or retries exhausted) background-job failure."""
    capture_exception(exc, job_id=job_id, job_kind=kind, attempts=attempts, area="background_job")
