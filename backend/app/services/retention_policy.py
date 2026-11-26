"""Pure retention rules (no third-party imports; unit tested)."""
from dataclasses import dataclass
from datetime import datetime, timedelta

# Audit actions with these prefixes are security records and are kept for the (longer) security retention period.
SECURITY_ACTION_PREFIXES = ("auth.", "admin.", "github.credentials", "account.", "workspace.", "security.")
JOB_DONE_STATUSES = ("succeeded", "cancelled")
INDEXING_DONE_STATUSES = ("completed", "failed", "cancelled")


@dataclass(frozen=True)
class RetentionPolicy:
    sessions_days: int
    webhook_days: int
    jobs_done_days: int
    jobs_failed_days: int
    indexing_jobs_days: int
    audit_days: int
    security_audit_days: int
    batch_size: int
    max_batches: int
    invitations_days: int = 30
    notifications_days: int = 90
    notifications_max_days: int = 365

    @classmethod
    def from_settings(cls, s) -> "RetentionPolicy":
        return cls(s.retention_sessions_days, s.retention_webhook_days, s.retention_jobs_done_days, s.retention_jobs_failed_days,
                   s.retention_indexing_jobs_days, s.retention_audit_days, s.retention_security_audit_days, s.cleanup_batch_size, s.cleanup_max_batches,
                   getattr(s, "retention_invitations_days", 30), getattr(s, "retention_notifications_days", 90), getattr(s, "retention_notifications_max_days", 365))

    def cutoffs(self, now: datetime) -> dict[str, datetime | None]:
        """None = rule disabled (days <= 0) - nothing is deleted for it."""
        def cut(days: int):
            return now - timedelta(days=days) if days > 0 else None
        return {"sessions": cut(self.sessions_days), "webhook_deliveries": cut(self.webhook_days), "jobs_done": cut(self.jobs_done_days),
                "jobs_failed": cut(self.jobs_failed_days), "indexing_jobs": cut(self.indexing_jobs_days),
                "audit_general": cut(self.audit_days), "audit_security": cut(self.security_audit_days),
                "invitations": cut(self.invitations_days), "notifications_read": cut(self.notifications_days), "notifications_any": cut(self.notifications_max_days)}


def is_security_action(action: str) -> bool:
    return action.startswith(SECURITY_ACTION_PREFIXES)
