"""Worker process: `python -m app.workers.runner` ; health: `python -m app.workers.runner --healthcheck`.

* Bounded concurrency (WORKER_CONCURRENCY threads), each job in its own DB session.
* Handler signature: handler(db: Session, job: BackgroundJob) -> None; raise to fail/retry.
* Retries/backoff/max-attempts/stale recovery live in services.job_queue.
* Timeouts are enforced by lease: a job running past its timeout is recovered by any worker;
  the original (zombie) result is then rejected by the fenced complete()/fail().
  Handlers should check job deadlines cooperatively (Python threads cannot be killed).
* Graceful shutdown: SIGTERM/SIGINT stop claiming new jobs and wait up to the grace period.
"""
import logging
import os
import signal
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import update

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.base import utcnow
from app.models import CodeReview
from app.services import job_queue
from app.services.job_policy import is_retriable
from app.workers.registry import load_handlers

log = logging.getLogger("synaxys.worker")


class Worker:
    def __init__(self, session_factory, handlers: dict, settings=None, worker_id: str | None = None):
        self.sf, self.handlers, self.s = session_factory, handlers, settings or get_settings()
        self.id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.stop = threading.Event()

    # -- single job, synchronous (used by run_forever threads and by tests) --
    def run_once(self) -> bool:
        with self.sf() as db:
            job = job_queue.claim_next(db, self.id, kinds=list(self.handlers) or None) if self.handlers else None
            if job is None:
                missing = job_queue.claim_next(db, self.id)  # job kinds with no handler must fail loudly
                if missing is None:
                    return False
                job = missing
        self._execute(job)
        return True

    def _execute(self, job) -> None:
        handler = self.handlers.get(job.kind)
        with self.sf() as db:
            if handler is None:
                job_queue.fail(db, job.id, self.id, f"No handler for job kind '{job.kind}' in this build", retriable=False)
                self._on_final_failure(db, job, f"No handler for job kind '{job.kind}'")
                return
            try:
                handler(db, job)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                outcome = job_queue.fail(db, job.id, self.id, exc, retriable=is_retriable(exc))
                log.warning("job %s (%s) failed -> %s", job.id, job.kind, outcome, extra={"extra_fields": {"job_id": job.id}})
                if outcome == "failed":
                    self._on_final_failure(db, job, str(exc))
                return
            job_queue.complete(db, job.id, self.id)

    def _on_final_failure(self, db, job, error: str) -> None:
        """Never leave a review in an endless 'queued/processing' state."""
        if job.kind == "review" and isinstance(job.payload, dict) and job.payload.get("review_id"):
            from app.services.job_policy import sanitize_error
            db.execute(update(CodeReview).where(CodeReview.id == job.payload["review_id"],
                                                CodeReview.status.in_(["queued", "processing"]))
                       .values(status="failed", error=sanitize_error(error), finished_at=utcnow()))
            db.commit()

    def heartbeat(self) -> None:
        try:
            with open(self.s.worker_heartbeat_path, "w") as fh:
                fh.write(str(time.time()))
        except OSError:
            log.warning("could not write heartbeat file")

    def run_forever(self) -> None:
        pool = ThreadPoolExecutor(max_workers=self.s.worker_concurrency, thread_name_prefix="job")
        active: set = set()
        last_recover = 0.0
        log.info("worker %s started (concurrency=%s, handlers=%s)", self.id, self.s.worker_concurrency, sorted(self.handlers))
        while not self.stop.is_set():
            self.heartbeat()
            active = {f for f in active if not f.done()}
            if time.monotonic() - last_recover > 30:
                with self.sf() as db:
                    for jid, outcome in job_queue.recover_stale(db):
                        log.warning("recovered stale job %s -> %s", jid, outcome)
                last_recover = time.monotonic()
            if len(active) < self.s.worker_concurrency:
                with self.sf() as db:
                    job = job_queue.claim_next(db, self.id)
                if job is not None:
                    active.add(pool.submit(self._execute, job))
                    continue
            self.stop.wait(self.s.worker_poll_interval_seconds)
        log.info("shutting down; waiting up to %ss for %d job(s)", self.s.worker_shutdown_grace_seconds, len(active))
        pool.shutdown(wait=False, cancel_futures=True)
        deadline = time.monotonic() + self.s.worker_shutdown_grace_seconds
        while any(not f.done() for f in active) and time.monotonic() < deadline:
            time.sleep(0.5)  # unfinished jobs are recovered by lease expiry


def healthcheck(max_age: float = 60.0) -> int:
    try:
        age = time.time() - float(open(get_settings().worker_heartbeat_path).read())
        return 0 if age < max_age else 1
    except (OSError, ValueError):
        return 1


def main() -> None:
    if "--healthcheck" in sys.argv:
        sys.exit(healthcheck())
    s = get_settings()
    configure_logging(s.log_level)
    from app.db.session import SessionLocal
    w = Worker(SessionLocal, load_handlers(), s)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: w.stop.set())
    w.run_forever()


if __name__ == "__main__":
    main()
