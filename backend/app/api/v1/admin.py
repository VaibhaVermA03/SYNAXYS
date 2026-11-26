"""Platform-admin API (ADMIN_GITHUB_IDS only; enforced here on the backend for every route via the router dependency).
Failed/background job monitoring backed by the real queue table."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import rate_limit, require_admin
from app.db.session import get_db
from app.models import User
from app.schemas.admin import AdminJobDetail, AdminJobPage, AdminJobStats
from app.services import admin_jobs

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/jobs", response_model=AdminJobPage)
def list_jobs(status: str | None = Query("failed", max_length=20), kind: str | None = Query(None, max_length=30),
              page: int = Query(1, ge=1, le=100000), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    """status defaults to 'failed'; pass an empty status for all."""
    return admin_jobs.list_jobs(db, status=status or None, kind=kind or None, page=page, page_size=page_size)


@router.get("/jobs/summary", response_model=AdminJobStats)
def summary(db: Session = Depends(get_db)):
    return admin_jobs.stats(db)


@router.get("/jobs/{job_id}", response_model=AdminJobDetail)
def job_detail(job_id: int, db: Session = Depends(get_db)):
    return admin_jobs.get_job(db, job_id)


@router.post("/jobs/{job_id}/retry", response_model=AdminJobDetail, status_code=202, dependencies=[Depends(rate_limit("admin_retry", 30, by="user"))])
def retry(job_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return admin_jobs.retry_job(db, admin, job_id)
