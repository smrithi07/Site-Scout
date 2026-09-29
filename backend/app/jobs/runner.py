"""Runs one claimed job step by step (Core rule 5: failed jobs name the failed step and resume
from it). A heartbeat thread proves the worker is alive; before committing any step the runner
re-checks it still holds the job (the "lease"), so a job the reaper handed to another worker is
never finished twice."""
import json
import logging
import threading

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import audit
from app.core.db import SessionLocal, engine
from app.jobs.context import StepContext
from app.jobs.registry import kinds
from app.models import Job, JobStep

log = logging.getLogger(__name__)


class LeaseLost(Exception):
    """The job was re-queued (heartbeat judged stale) and may now belong to another worker."""


class Heartbeat(threading.Thread):
    def __init__(self, job_id: int, worker_id: str, every: float):
        super().__init__(daemon=True, name=f"heartbeat-{job_id}")
        self.job_id, self.worker_id, self.every = job_id, worker_id, every
        self.stop_event = threading.Event()
        self.lost = False

    def run(self) -> None:
        while not self.stop_event.wait(self.every):
            with engine.begin() as conn:
                n = conn.execute(text("""UPDATE jobs SET heartbeat_at = now()
                                         WHERE id = :id AND locked_by = :w AND status = 'running'"""),
                                 dict(id=self.job_id, w=self.worker_id)).rowcount
            if n == 0:
                self.lost = True
                return

    def stop(self) -> None:
        self.stop_event.set()
        self.join(timeout=self.every + 1)


def hold_lease(db: Session, job_id: int, worker_id: str) -> None:
    """Row-lock the job and confirm this worker still owns it — inside the transaction that is
    about to commit a step, so ownership can't change between the check and the commit."""
    owner = db.execute(text("SELECT locked_by FROM jobs WHERE id = :id AND status = 'running' FOR UPDATE"),
                       dict(id=job_id)).scalar()
    if owner != worker_id:
        raise LeaseLost(f"job {job_id} now held by {owner!r}")


def execute(job_id: int, worker_id: str, heartbeat_seconds: float) -> str:
    """Returns 'succeeded' | 'failed' | 'lease_lost'."""
    hb = Heartbeat(job_id, worker_id, heartbeat_seconds)
    hb.start()
    try:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            kind, payload = job.kind, job.payload
            steps = [(s.idx, s.name, s.status, s.output) for s in
                     db.query(JobStep).filter(JobStep.job_id == job_id).order_by(JobStep.idx)]
        if kind not in kinds():
            # Fail the job cleanly (never crash the worker): usually a worker running older code.
            idx, name = next(((i, n) for i, n, st, _ in steps if st != "done"), (steps[0][0], steps[0][1]))
            _start_step(job_id, idx, name, worker_id)
            _fail(job_id, idx, name, worker_id, LookupError(f"unknown job kind {kind!r} — is the worker running current code?"))
            return "failed"
        functions = dict(kinds()[kind])
        outputs = {name: out for _, name, status, out in steps if status == "done"}

        for idx, name, status, _ in steps:
            if status == "done":
                continue  # resume: never re-run a finished step
            attempt = _start_step(job_id, idx, name, worker_id)
            try:
                with SessionLocal() as db, db.begin():
                    out = functions[name](StepContext(job_id, payload, dict(outputs), attempt, db)) or {}
                    hold_lease(db, job_id, worker_id)
                    db.execute(text("""UPDATE job_steps SET status = 'done', output = CAST(:o AS jsonb), error = NULL,
                                              finished_at = now() WHERE job_id = :id AND idx = :idx"""),
                               dict(o=_json(out), id=job_id, idx=idx))
            except LeaseLost as exc:
                log.warning("job %s: lease lost during %s (%s); abandoning", job_id, name, exc)
                return "lease_lost"
            except Exception as exc:  # the step's own transaction has rolled back
                log.exception("job %s: step %s failed", job_id, name)
                _fail(job_id, idx, name, worker_id, exc)
                return "failed"
            # Later steps see exactly what was persisted — the same value a resumed run would load.
            outputs[name] = json.loads(_json(out))

        _succeed(job_id, worker_id)
        return "succeeded"
    finally:
        hb.stop()


def _start_step(job_id: int, idx: int, name: str, worker_id: str) -> int:
    with SessionLocal() as db, db.begin():
        hold_lease(db, job_id, worker_id)
        db.execute(text("UPDATE jobs SET current_step = :n WHERE id = :id"), dict(n=name, id=job_id))
        return db.execute(text("""UPDATE job_steps SET status = 'running', attempts = attempts + 1,
                                         started_at = now(), finished_at = NULL
                                  WHERE job_id = :id AND idx = :idx RETURNING attempts"""),
                          dict(id=job_id, idx=idx)).scalar()


def _fail(job_id: int, idx: int, name: str, worker_id: str, exc: Exception) -> None:
    message = f"{type(exc).__name__}: {exc}"[:2000]
    try:
        with SessionLocal() as db, db.begin():
            hold_lease(db, job_id, worker_id)
            db.execute(text("""UPDATE job_steps SET status = 'failed', error = :e, finished_at = now()
                               WHERE job_id = :id AND idx = :idx"""), dict(e=message, id=job_id, idx=idx))
            db.execute(text("""UPDATE jobs SET status = 'failed', error = :e, finished_at = now(),
                                      locked_by = NULL, version = version + 1 WHERE id = :id"""),
                       dict(e=f"{name}: {message}", id=job_id))
            audit.record(db, actor=None, entity_type="job", entity_id=job_id, action="failed",
                         from_state="running", to_state="failed", reason=f"step {name} failed: {message}",
                         details={"step": name})
    except LeaseLost:
        log.warning("job %s: lease lost before recording failure of %s", job_id, name)


def _succeed(job_id: int, worker_id: str) -> None:
    with SessionLocal() as db, db.begin():
        hold_lease(db, job_id, worker_id)
        db.execute(text("""UPDATE jobs SET status = 'succeeded', current_step = NULL, finished_at = now(),
                                  locked_by = NULL, version = version + 1 WHERE id = :id"""), dict(id=job_id))
        audit.record(db, actor=None, entity_type="job", entity_id=job_id, action="succeeded",
                     from_state="running", to_state="succeeded", reason="all steps completed")


def _json(value: dict) -> str:
    return json.dumps(value, default=str)
