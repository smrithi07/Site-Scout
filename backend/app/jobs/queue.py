"""Job queue on Postgres: enqueue, claim (row locking), reap (lost heartbeats), retry.
Every job status change writes an audit event in the same transaction."""
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core import audit
from app.core.db import engine
from app.core.errors import Conflict, NotFound
from app.core.locking import update_versioned
from app.jobs.registry import KINDS
from app.models import Job, JobStep, User


def enqueue(db: Session, kind: str, payload: dict, actor: User | None, queue: str = "default") -> Job:
    """Adds the job and its pending steps to `db` (caller commits)."""
    if kind not in KINDS:
        raise ValueError(f"unknown job kind {kind!r}")
    job = Job(kind=kind, queue=queue, payload=payload, created_by=actor.id if actor else None)
    db.add(job)
    db.flush()
    db.add_all(JobStep(job_id=job.id, idx=i, name=name) for i, (name, _) in enumerate(KINDS[kind]))
    audit.record(db, actor=actor, entity_type="job", entity_id=job.id, action="created",
                 to_state="queued", reason=f"{kind} requested", details={"queue": queue})
    db.flush()
    db.refresh(job)
    return job


def claim(worker_id: str, queues: list[str]) -> int | None:
    """Atomically take the oldest runnable job. SKIP LOCKED: concurrent workers never block on,
    or double-claim, the same row."""
    with engine.begin() as conn:
        row = conn.execute(text("""
            UPDATE jobs SET status = 'running', locked_by = :w, attempts = attempts + 1,
                   heartbeat_at = now(), started_at = coalesce(started_at, now()), version = version + 1
            WHERE id = (SELECT id FROM jobs
                        WHERE status = 'queued' AND queue = ANY(:q) AND run_after <= now()
                        ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1)
            RETURNING id, attempts"""), dict(w=worker_id, q=queues)).one_or_none()
        if row is None:
            return None
        audit.record(conn, actor=None, entity_type="job", entity_id=row.id, action="started",
                     from_state="queued", to_state="running",
                     reason=f"claimed by worker {worker_id} (attempt {row.attempts})")
        return row.id


def reap(queues: list[str], stale_after_seconds: float, max_attempts: int) -> list[int]:
    """Re-queue running jobs whose worker stopped heart-beating (crashed/killed). Done steps keep
    their outputs, so the job resumes from where it stopped. Past `max_attempts` it fails."""
    with engine.begin() as conn:
        rows = conn.execute(text("""
            WITH stale AS (
                SELECT id, locked_by, attempts FROM jobs
                WHERE status = 'running' AND queue = ANY(:q)
                  AND heartbeat_at < now() - make_interval(secs => :stale)
                FOR UPDATE SKIP LOCKED)
            UPDATE jobs j SET
                status = CASE WHEN stale.attempts >= :max THEN 'failed' ELSE 'queued' END,
                error = CASE WHEN stale.attempts >= :max
                             THEN coalesce(j.current_step, 'job') || ': worker heartbeat lost ' || stale.attempts || ' times'
                             ELSE j.error END,
                finished_at = CASE WHEN stale.attempts >= :max THEN now() END,
                locked_by = NULL, version = j.version + 1
            FROM stale WHERE j.id = stale.id
            RETURNING j.id, j.status, stale.locked_by, stale.attempts"""),
            dict(q=queues, stale=stale_after_seconds, max=max_attempts)).all()
        if rows:
            # The dead worker's step never committed (its transaction died with it).
            conn.execute(text("UPDATE job_steps SET status = 'pending' WHERE job_id = ANY(:ids) AND status = 'running'"),
                         dict(ids=[r.id for r in rows]))
        for r in rows:
            audit.record(conn, actor=None, entity_type="job", entity_id=r.id,
                         action="requeued" if r.status == "queued" else "failed",
                         from_state="running", to_state=r.status,
                         reason=f"no heartbeat from worker {r.locked_by} for >{stale_after_seconds:g}s "
                                f"(attempt {r.attempts} of {max_attempts})")
        return [r.id for r in rows]


def retry(db: Session, job_id: int, actor: User, reason: str, expected_version: int | None = None) -> Job:
    """Manual retry of a failed job: resumes at the failed step; done steps are not re-run."""
    job = get(db, job_id)
    if job.status != "failed":
        raise Conflict(f"job {job_id} is {job.status}; only failed jobs can be retried")
    changes = dict(status="queued", error=None, locked_by=None, attempts=0, finished_at=None,
                   run_after=text("now()"))
    if expected_version is not None:
        update_versioned(db, Job, job_id, expected_version, **changes)
    else:
        db.execute(update(Job).where(Job.id == job_id).values(**changes, version=Job.version + 1))
    db.execute(update(JobStep).where(JobStep.job_id == job_id, JobStep.status.in_(("failed", "running")))
               .values(status="pending", error=None))
    audit.record(db, actor=actor, entity_type="job", entity_id=job_id, action="retried",
                 from_state="failed", to_state="queued", reason=reason,
                 details={"failed_step": job.current_step, "error": job.error})
    db.flush()
    db.refresh(job)
    return job


def get(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise NotFound(f"job {job_id} not found")
    return job


def steps(db: Session, job_id: int) -> list[JobStep]:
    return list(db.scalars(select(JobStep).where(JobStep.job_id == job_id).order_by(JobStep.idx)))
