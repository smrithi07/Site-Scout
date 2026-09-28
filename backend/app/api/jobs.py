"""Job progress + retry (the UI's step list and retry button), and the audit trail."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import Role, current_user, require_roles
from app.core.db import get_db
from app.jobs import queue
from app.models import AuditEvent, Job, User
from app.schemas.jobs import AuditEventOut, JobOut, RetryIn, SelftestIn

router = APIRouter(tags=["jobs"])

MANAGERS = (Role.BD_MANAGER, Role.SURVEY_MANAGER)


def _visible_job(db: Session, job_id: int, user: User) -> Job:
    job = queue.get(db, job_id)
    if job.created_by != user.id and user.role not in MANAGERS:
        raise HTTPException(403, "Only the job's creator or a manager can see this job")
    return job


def _out(db: Session, job: Job) -> JobOut:
    return JobOut.model_validate({**{c: getattr(job, c) for c in JobOut.model_fields if c != "steps"},
                                  "steps": queue.steps(db, job.id)})


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _out(db, _visible_job(db, job_id, user))


@router.post("/jobs/{job_id}/retry", response_model=JobOut)
def retry_job(job_id: int, body: RetryIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _visible_job(db, job_id, user)
    job = queue.retry(db, job_id, user, body.reason, body.version)
    db.commit()
    return _out(db, job)


@router.post("/jobs/selftest", response_model=JobOut, status_code=202)
def start_selftest(body: SelftestIn, user: User = Depends(require_roles(Role.BD_MANAGER)),
                   db: Session = Depends(get_db)):
    """Demo/diagnostic: a 3-step job with optional injected failure, to show fail → retry → resume."""
    job = queue.enqueue(db, "selftest", body.model_dump(exclude_none=True), user)
    db.commit()
    return _out(db, job)


@router.get("/audit", response_model=list[AuditEventOut], dependencies=[Depends(require_roles(*MANAGERS))])
def audit_trail(entity_type: str, entity_id: str, limit: int = Query(200, le=1000),
                db: Session = Depends(get_db)):
    return db.scalars(select(AuditEvent)
                      .where(AuditEvent.entity_type == entity_type, AuditEvent.entity_id == entity_id)
                      .order_by(AuditEvent.id).limit(limit)).all()
