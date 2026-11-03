"""Executes one review: fetch PR files -> run the bounded engine -> persist findings + DRAFT comments.

Nothing is published to GitHub here. On any failure the review returns to 'queued' with a sanitized
note and the exception propagates, so the worker's retry/backoff applies; the worker marks the review
'failed' only after the final attempt (no endless 'processing').
"""
import time

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.agents.review_graph import Limits, ReviewInput, run_review
from app.core.config import Settings
from app.core.exceptions import BadRequest, NotConfigured
from app.db.base import utcnow
from app.models import (AuditLog, CodeReview, GitHubInstallation, PullRequest, Repository, RepositoryAccess, ReviewComment, ReviewFinding,
                        ReviewRule)
from app.services import job_queue
from app.services.context_retrieval import build_queries, retrieve_context
from app.services.comment_service import format_inline_comment
from app.services.job_policy import sanitize_error


def load_rules(db: Session, repo: Repository) -> list[dict]:
    """Enabled rules scoped to this repo, plus global rules authored by one of its admins."""
    owners = select(RepositoryAccess.user_id).where(RepositoryAccess.repository_id == repo.id, RepositoryAccess.role == "owner")
    rules = db.scalars(select(ReviewRule).where(ReviewRule.enabled.is_(True),
                                                 or_(ReviewRule.repository_id == repo.id,
                                                     (ReviewRule.repository_id.is_(None)) & ReviewRule.owner_user_id.in_(owners)))).all()
    return [{"name": r.name, "severity": r.severity, "instruction": r.instruction, "languages": r.languages or [],
             "file_patterns": r.file_patterns or [], "enabled": True} for r in rules]


def _limits(s: Settings, repo: Repository) -> Limits:
    cfg = repo.config
    return Limits(batch_chars=s.review_batch_chars, total_chars=s.review_total_chars, max_batches=s.review_max_batches,
                  max_files=cfg.max_files if cfg else s.review_max_files, max_patch_bytes=cfg.max_patch_bytes if cfg else s.review_max_patch_bytes,
                  min_confidence=s.review_min_confidence, max_findings=s.review_max_findings)


def _context_provider(s: Settings, repo: Repository, note: dict):
    """Lazy retriever; never raises and never hides what happened (note ends up in the review summary)."""
    from app.services.embedding_service import get_embedder
    from app.services.vector_service import get_vector_store, indexing_available

    def provider(eligible: list[dict]) -> list[dict]:
        if not s.context_retrieval_enabled or not (repo.config is None or repo.config.index_enabled):
            note["text"] = "Cross-file context: disabled for this repository."
            return []
        if repo.index_status != "indexed":
            note["text"] = "Cross-file context: not used (repository is not indexed yet); only the diff was reviewed."
            return []
        ok, reason = indexing_available(s)
        if not ok:
            note["text"] = f"Cross-file context: unavailable ({reason})."
            return []
        try:
            snippets = retrieve_context(repo_id=repo.id, branch=repo.default_branch, changed_paths={d["path"] for d in eligible},
                                        queries=build_queries(eligible), store=get_vector_store(s), embedder=get_embedder(s), min_score=s.context_min_score)
        except Exception as exc:  # noqa: BLE001
            note["text"] = f"Cross-file context: retrieval failed ({type(exc).__name__}); only the diff was reviewed."
            return []
        note["text"] = f"Cross-file context: {len(snippets)} related snippet(s) from the repository index were provided to the model." if snippets else \
            "Cross-file context: index searched, no sufficiently related code found."
        return snippets
    return provider


def _cancel(db: Session, review: CodeReview, reason: str) -> str:
    review.status, review.error, review.finished_at = "cancelled", reason, utcnow()
    db.commit()
    return "cancelled"


def execute_review(db: Session, s: Settings, review_id: int, gh, llm_factory, *, deadline_seconds: float = 540.0) -> str:
    review = db.get(CodeReview, review_id)
    if review is None:
        return "missing"
    if review.status in ("completed", "cancelled"):
        return review.status  # idempotent re-delivery of an already finished job
    pr = db.get(PullRequest, review.pull_request_id)
    repo = db.get(Repository, pr.repository_id)
    if pr.is_demo:
        raise BadRequest("Demo pull requests cannot be reviewed.", code="demo_readonly")
    if review.head_sha != pr.head_sha:
        return _cancel(db, review, "Superseded by a newer commit")
    if not repo.is_enabled:
        return _cancel(db, review, "Repository was disconnected")

    started = time.monotonic()
    review.status, review.started_at, review.error = "processing", utcnow(), None
    db.commit()
    try:
        llm = llm_factory(s)
        if not s.github_app_configured:
            raise NotConfigured("GitHub App is not configured; cannot fetch pull request files.", code="github_app_not_configured")
        inst = db.get(GitHubInstallation, repo.installation_id)
        files = gh.list_pull_request_files(gh.installation_token(inst.installation_id), repo.full_name, pr.number)
        note: dict = {}
        result = run_review(ReviewInput(repo_id=repo.id, pr_number=pr.number, pr_title=pr.title, base_branch=pr.base_branch, head_branch=pr.head_branch,
                                        files=files, rules=load_rules(db, repo), context_fn=_context_provider(s, repo, note)), llm, _limits(s, repo), deadline=started + deadline_seconds)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        failed = db.get(CodeReview, review_id)
        failed.status, failed.error = "queued", f"Will retry: {sanitize_error(exc, 300)}"
        db.commit()
        raise

    review = db.get(CodeReview, review_id)
    if review.status == "cancelled":  # cancelled while the model was running: discard results
        return "cancelled"
    review.findings.clear()
    db.flush()
    for f in result.findings:
        row = ReviewFinding(review_id=review.id, fingerprint=f["fingerprint"], category=f["category"], severity=f["severity"], title=f["title"],
                            explanation=f["explanation"], evidence=f["evidence"], path=f["path"], start_line=f["start_line"], end_line=f["end_line"],
                            remediation=f["remediation"], patch=f["patch"], confidence=f["confidence"], inline_possible=f["inline_possible"])
        if f["inline_possible"]:  # only findings with a verified diff location get a proposed inline comment
            row.comment = ReviewComment(body=format_inline_comment(f), state="draft")
        db.add(row)
    review.summary, review.model = (result.summary + (" " + note["text"] if note.get("text") else "")), result.model[:80]
    review.status, review.finished_at, review.duration_ms = "completed", utcnow(), int((time.monotonic() - started) * 1000)
    db.add(AuditLog(action="review.completed", target_type="review", target_id=str(review.id), meta={"findings": len(result.findings), **{k: v for k, v in result.stats.items() if isinstance(v, int)}}))
    if repo.config and repo.config.auto_publish and any(f["inline_possible"] for f in result.findings):  # owner-enabled policy only
        job_queue.enqueue(db, "publish", {"review_id": review.id}, f"publish:{review.id}:auto", timeout_seconds=300)
    db.commit()
    return "completed"
