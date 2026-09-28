"""Worker process: `python -m app.jobs.worker`. Loop: re-queue jobs with dead heartbeats, claim
the next job, run it step by step. No Celery/Redis — see docs/DESIGN.md §1."""
import logging
import os
import socket
import time

from app.core.config import load_config, register_config
from app.core.db import engine
from app.jobs import queue, runner

logging.basicConfig(level=logging.INFO, format="%(asctime)s worker %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def run_once(worker_id: str, cfg: dict | None = None) -> tuple[int, str] | None:
    """One iteration. Returns (job_id, outcome) if a job ran, else None. Used by tests too."""
    cfg = cfg or load_config()["jobs"]
    for job_id in queue.reap(cfg["queues"], cfg["stale_after_seconds"], cfg["max_attempts"]):
        log.warning("job %s: heartbeat lost, re-queued or failed", job_id)
    job_id = queue.claim(worker_id, cfg["queues"])
    if job_id is None:
        return None
    outcome = runner.execute(job_id, worker_id, cfg["heartbeat_seconds"])
    log.info("job %s: %s", job_id, outcome)
    return job_id, outcome


def main() -> None:
    with engine.begin() as conn:
        register_config(conn)
    cfg = load_config()["jobs"]
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    log.info("worker %s serving queues %s", worker_id, cfg["queues"])
    while True:
        if run_once(worker_id, cfg) is None:
            time.sleep(cfg["poll_seconds"])


if __name__ == "__main__":
    main()
