"""Structured JSON logging with secret redaction applied to every record, plus request/job correlation ids."""
import json
import logging
from contextvars import ContextVar

from app.core.security import redact_secrets

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
job_id_var: ContextVar[str | None] = ContextVar("job_id", default=None)


class RedactingJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"), "level": record.levelname,
                   "logger": record.name, "msg": redact_secrets(record.getMessage())}
        if request_id_var.get():
            payload["request_id"] = request_id_var.get()
        if job_id_var.get():
            payload["job_id"] = job_id_var.get()
        if record.exc_info:
            payload["exc"] = redact_secrets(self.formatException(record.exc_info))
        for k, v in getattr(record, "extra_fields", {}).items():
            payload[k] = redact_secrets(str(v))
        return json.dumps(payload)


def configure_logging(level: str = "INFO") -> None:
    h = logging.StreamHandler()
    h.setFormatter(RedactingJsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level.upper())
