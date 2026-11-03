from app.core.config import get_settings
from app.services.github_service import GitHubClient
from app.services.publish_service import auto_publish_review


def handle_publish(db, job) -> None:
    """Job kind 'publish' (auto-publish policy). GitHub/transient errors raise so queue retry applies."""
    s = get_settings()
    auto_publish_review(db, s, GitHubClient(s), int(job.payload["review_id"]))
