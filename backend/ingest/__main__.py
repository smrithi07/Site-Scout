"""Offline ingest CLI. Never imported by the API or worker at request time.

    python -m ingest build    # new data snapshot with all reference data; marks it `ready`

Each build creates a fresh snapshot (old ones stay — saved reports point at them). Each step
commits on its own; on failure the snapshot is marked `failed` with the step name and error.
"""
import argparse
import json
import sys
import time

from sqlalchemy import text

from app.core.config import load_config
from app.core.db import engine
from ingest.grid import build_grid
from ingest.localities import build_localities
from ingest.reference import (
    build_service_area,
    load_pincodes,
    load_post_offices,
    load_stores,
    load_wards,
    load_zones,
)

STEPS = [load_zones, load_wards, build_service_area, load_post_offices, load_pincodes,
         load_stores, build_grid, build_localities]


def build() -> int:
    with engine.begin() as conn:
        s = conn.execute(text("""INSERT INTO data_snapshots (status, config_version, stats)
                                 VALUES ('building', :v, '{}') RETURNING id"""),
                         dict(v=load_config()["version"])).scalar()
    print(f"snapshot {s}: building")
    stats: dict = {}
    for step in STEPS:
        t0 = time.monotonic()
        try:
            with engine.begin() as conn:
                result = step(conn, s)
        except Exception as exc:
            with engine.begin() as conn:
                conn.execute(text("""UPDATE data_snapshots SET status='failed', finished_at=now(),
                                     error=:e, stats=CAST(:st AS jsonb) WHERE id=:s"""),
                             dict(s=s, e=f"{step.__name__}: {exc}", st=json.dumps(stats)))
            print(f"snapshot {s}: FAILED at {step.__name__}: {exc}", file=sys.stderr)
            return 1
        stats.update(result)
        print(f"  {step.__name__:<20} {time.monotonic() - t0:5.1f}s  {result}")
    with engine.begin() as conn:
        conn.execute(text("""UPDATE data_snapshots SET status='ready', finished_at=now(),
                             stats=CAST(:st AS jsonb) WHERE id=:s"""), dict(s=s, st=json.dumps(stats)))
    print(f"snapshot {s}: ready")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m ingest")
    parser.add_argument("command", choices=["build"])
    parser.parse_args()
    return build()


if __name__ == "__main__":
    sys.exit(main())
