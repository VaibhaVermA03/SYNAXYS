"""Structured JSON logging with secret redaction applied to every record."""
import json
import logging

from app.core.security import redact_secrets


class RedactingJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"), "level": record.levelname,
                   "logger": record.name, "msg": redact_secrets(record.getMessage())}
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
