"""Worker process. Phase 0c placeholder: proves it can reach the DB and stays alive.
The jobs table, row-locking poll, heartbeat, and step resume arrive in Phase 3."""
import logging
import time

from sqlalchemy import text

from app.core.db import engine
from app.core.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s worker %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    log.info("connected to db; idle (no jobs table yet)")
    while True:
        time.sleep(get_settings().worker_poll_seconds)


if __name__ == "__main__":
    main()
