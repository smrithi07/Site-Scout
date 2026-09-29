"""Offline ingest CLI. Never imported by the API or worker at request time.

    python -m ingest build    # new data snapshot: reference data + OSM + cell features; marks it `ready`
    python -m ingest build --if-empty   # …only if no `ready` snapshot exists yet (used by `make setup`)
    python -m ingest gate     # Phase 2 data-quality report on the active snapshot (read-only)
    python -m ingest prune    # delete `failed` snapshots and their partial rows

Each build creates a fresh snapshot (old ones stay — saved reports point at them). Each step
commits on its own; on failure the snapshot is marked `failed` with the step name and error.
"""
import argparse
import json
import sys
import time

from sqlalchemy import text

from app.core.config import load_config, register_config
from app.core.db import engine
from ingest import gate as gate_report
from ingest.features import build_cell_features
from ingest.grid import build_grid
from ingest.localities import build_localities
from ingest.ml_buildings import load_ml_buildings
from ingest.osm import load_osm
from ingest.reference import (
    build_service_area,
    load_pincodes,
    load_post_offices,
    load_stores,
    load_wards,
    load_zones,
)

STEPS = [load_zones, load_wards, build_service_area, load_post_offices, load_pincodes,
         load_stores, build_grid, load_osm, load_ml_buildings, build_cell_features, build_localities]


def build(if_empty: bool = False) -> int:
    if if_empty:
        with engine.begin() as conn:
            ready = conn.execute(text("SELECT max(id) FROM data_snapshots WHERE status = 'ready'")).scalar()
        if ready is not None:
            print(f"snapshot {ready} is ready; nothing to build (run without --if-empty for a new snapshot)")
            return 0
    with engine.begin() as conn:
        register_config(conn)  # the version stamped on the snapshot must be a registered one
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


def gate() -> int:
    with engine.begin() as conn:
        s = conn.execute(text("SELECT max(id) FROM data_snapshots WHERE status = 'ready'")).scalar()
        print(json.dumps(gate_report.run(conn, s), indent=2, default=float))
    return 0


def prune() -> int:
    with engine.begin() as conn:
        ids = conn.execute(text("DELETE FROM data_snapshots WHERE status = 'failed' RETURNING id")).scalars().all()
    print(f"pruned failed snapshots: {sorted(ids) or 'none'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m ingest")
    parser.add_argument("command", choices=["build", "gate", "prune"])
    parser.add_argument("--if-empty", action="store_true", help="build: skip if a ready snapshot exists")
    args = parser.parse_args()
    if args.command == "build":
        return build(args.if_empty)
    return {"gate": gate, "prune": prune}[args.command]()


if __name__ == "__main__":
    sys.exit(main())
