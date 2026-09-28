"""Phase 3b checkpoint: a job that fails at a step resumes from that step; a job whose worker
died is re-queued by the heartbeat reaper and finishes without redoing finished steps.
Runs on queue 'test' so the live worker container (queue 'default') never touches these jobs."""
import threading
import time

import pytest
from sqlalchemy import text

from app.core.auth import Role
from app.core.db import SessionLocal, engine
from app.core.errors import Conflict
from app.core.locking import StaleVersion
from app.jobs import queue, runner
from app.jobs.worker import run_once
from app.models import Job, User
from tests.conftest import USER_IDS, headers

CFG = {"queues": ["test"], "poll_seconds": 0.1, "heartbeat_seconds": 0.3,
       "stale_after_seconds": 1.0, "max_attempts": 3}


@pytest.fixture(autouse=True)
def clean_test_queue():
    # Audit rows for these jobs stay (the log is append-only by design); the jobs themselves go.
    yield
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM jobs WHERE queue = 'test'"))


def _enqueue(payload: dict | None = None) -> int:
    with SessionLocal() as db:
        actor = db.get(User, USER_IDS[Role.BD_MANAGER])
        job = queue.enqueue(db, "selftest", payload or {}, actor, queue="test")
        db.commit()
        return job.id


def _state(job_id: int) -> tuple[Job, dict]:
    with SessionLocal() as db:
        job = queue.get(db, job_id)
        return job, {s.name: s for s in queue.steps(db, job_id)}


def _audit_actions(job_id: int) -> list[str]:
    with engine.connect() as conn:
        return conn.execute(text("SELECT action FROM audit_events WHERE entity_type = 'job' AND entity_id = :id "
                                 "ORDER BY id"), dict(id=str(job_id))).scalars().all()


def test_happy_path_runs_all_steps_in_order():
    job_id = _enqueue()
    assert run_once("w-test", CFG) == (job_id, "succeeded")
    job, steps = _state(job_id)
    assert job.status == "succeeded" and job.locked_by is None
    assert steps["save"].output["saw_outputs_of"] == ["compute", "prepare"]
    assert _audit_actions(job_id) == ["created", "started", "succeeded"]


def test_failed_step_is_named_and_retry_resumes_from_it():
    job_id = _enqueue({"fail_at": "compute", "fail_times": 1})
    assert run_once("w-test", CFG) == (job_id, "failed")
    job, steps = _state(job_id)
    assert job.status == "failed" and job.error.startswith("compute: RuntimeError")
    assert (steps["prepare"].status, steps["compute"].status, steps["save"].status) == ("done", "failed", "pending")
    prepare_output = steps["prepare"].output

    with SessionLocal() as db:
        queue.retry(db, job_id, db.get(User, USER_IDS[Role.BD_MANAGER]), "transient, retry")
        db.commit()
    assert run_once("w-test", CFG) == (job_id, "succeeded")
    job, steps = _state(job_id)
    assert steps["prepare"].attempts == 1 and steps["prepare"].output == prepare_output  # not re-run
    assert steps["compute"].attempts == 2
    assert steps["compute"].output["saw_outputs_of"] == ["prepare"]  # got the persisted output
    assert _audit_actions(job_id) == ["created", "started", "failed", "retried", "started", "succeeded"]


def test_dead_worker_job_is_requeued_and_resumes():
    job_id = _enqueue()
    # Worker A claims the job, finishes `prepare`, then "dies" before `compute`.
    assert queue.claim("w-dead", CFG["queues"]) == job_id
    with SessionLocal() as db, db.begin():
        db.execute(text("UPDATE job_steps SET status='done', attempts=1, output='{\"step\":\"prepare\"}' "
                        "WHERE job_id=:id AND name='prepare'"), dict(id=job_id))
        db.execute(text("UPDATE job_steps SET status='running', attempts=1 WHERE job_id=:id AND name='compute'"),
                   dict(id=job_id))
        db.execute(text("UPDATE jobs SET heartbeat_at = now() - interval '1 hour' WHERE id=:id"), dict(id=job_id))

    # Worker B's next iteration reaps it, claims it, and finishes from `compute`.
    assert run_once("w-alive", CFG) == (job_id, "succeeded")
    job, steps = _state(job_id)
    assert job.attempts == 2
    assert steps["prepare"].attempts == 1  # finished work was kept
    assert steps["compute"].attempts == 2  # the interrupted step re-ran
    assert "requeued" in _audit_actions(job_id)

    # And the dead worker, should it wake up, can no longer commit anything for this job.
    with SessionLocal() as db, db.begin(), pytest.raises(runner.LeaseLost):
        runner.hold_lease(db, job_id, "w-dead")


def test_heartbeat_keeps_a_slow_job_alive():
    # The step takes 2.5s, far past stale_after (1s); only the heartbeat stops the reaper.
    job_id = _enqueue({"sleep_in": "compute", "sleep_seconds": 2.5})
    result = {}
    t = threading.Thread(target=lambda: result.update(r=run_once("w-slow", CFG)))
    t.start()
    time.sleep(1.8)
    assert queue.reap(CFG["queues"], CFG["stale_after_seconds"], CFG["max_attempts"]) == []
    t.join(timeout=10)
    assert result["r"] == (job_id, "succeeded")


def test_job_fails_for_good_after_max_lost_heartbeats():
    job_id = _enqueue()
    for attempt in range(1, CFG["max_attempts"] + 1):
        assert queue.claim(f"w-crash-{attempt}", CFG["queues"]) == job_id
        with engine.begin() as conn:
            conn.execute(text("UPDATE jobs SET heartbeat_at = now() - interval '1 hour' WHERE id=:id"), dict(id=job_id))
        queue.reap(CFG["queues"], CFG["stale_after_seconds"], CFG["max_attempts"])
    job, _ = _state(job_id)
    assert job.status == "failed" and "heartbeat lost 3 times" in job.error


def test_two_workers_never_claim_the_same_job():
    job_id = _enqueue()
    barrier, got = threading.Barrier(4), []

    def grab(i: int) -> None:
        barrier.wait()
        got.append(queue.claim(f"w-race-{i}", CFG["queues"]))

    threads = [threading.Thread(target=grab, args=(i,)) for i in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(got, key=lambda x: x or 0) == [None, None, None, job_id]


def test_only_failed_jobs_can_be_retried_and_stale_versions_conflict():
    job_id = _enqueue({"fail_at": "save"})
    with SessionLocal() as db:
        actor = db.get(User, USER_IDS[Role.BD_MANAGER])
        with pytest.raises(Conflict):
            queue.retry(db, job_id, actor, "not failed yet")
    run_once("w-test", CFG)
    with SessionLocal() as db:
        actor = db.get(User, USER_IDS[Role.BD_MANAGER])
        with pytest.raises(StaleVersion):
            queue.retry(db, job_id, actor, "retry", expected_version=1)  # someone else moved it on
        db.rollback()
        current = queue.get(db, job_id).version
        assert queue.retry(db, job_id, actor, "retry", expected_version=current).status == "queued"
        db.commit()


def test_job_api_access_and_retry_conflict(client):
    job_id = _enqueue({"fail_at": "prepare"})
    run_once("w-test", CFG)
    # Visible to its creator (BD Manager) and to the Survey Manager; not to executives.
    assert client.get(f"/jobs/{job_id}", headers=headers(Role.BD_MANAGER)).json()["error"].startswith("prepare:")
    assert client.get(f"/jobs/{job_id}", headers=headers(Role.SURVEY_MANAGER)).status_code == 200
    assert client.get(f"/jobs/{job_id}", headers=headers(Role.BD_EXECUTIVE)).status_code == 403
    stale = client.post(f"/jobs/{job_id}/retry", headers=headers(Role.BD_MANAGER),
                        json={"reason": "retry please", "version": 1})
    assert stale.status_code == 409
    assert client.post("/jobs/selftest", headers=headers(Role.SURVEY_EXECUTIVE), json={}).status_code == 403
