from app.agents.llm import get_review_llm
from app.core.config import get_settings
from app.services.github_service import GitHubClient
from app.services.review_service import execute_review


def handle_review(db, job) -> None:
    """Job handler for kind='review'. Raises on failure so queue retry/backoff and fail-fast rules apply."""
    s = get_settings()
    execute_review(db, s, int(job.payload["review_id"]), GitHubClient(s), get_review_llm, deadline_seconds=max(30, job.timeout_seconds - 30))
