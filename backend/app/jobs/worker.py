"""Worker process. Placeholder until Phase 3b: registers the config version and stays alive.
The jobs table, row-locking poll, heartbeat, and step resume arrive in Phase 3b."""
import logging
import time

from app.core.config import register_config
from app.core.db import engine
from app.core.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s worker %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> None:
    with engine.begin() as conn:
        register_config(conn)
    log.info("connected to db; idle (no jobs table yet)")
    while True:
        time.sleep(get_settings().worker_poll_seconds)


if __name__ == "__main__":
    main()
