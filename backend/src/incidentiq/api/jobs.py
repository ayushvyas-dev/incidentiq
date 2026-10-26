"""Background job status endpoint."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from incidentiq.api.dependencies import get_db_session
from incidentiq.models import Job

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}")
def get_job(job_id: UUID, session: Session = Depends(get_db_session)):
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": str(job.id),
        "job_type": job.job_type,
        "status": job.status,
        "progress": job.progress,
        "error": {"code": job.error_code} if job.error_code else None,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
    }
