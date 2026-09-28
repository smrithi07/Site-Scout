"""Seed synthetic PAST lane captures around a property, so reuse can be demonstrated before any real
survey exists. Every row is `source = 'demo_seed'` (provenance: mock) — the UI and the roll-up
label it as such. Deterministic (fixed RNG seed) and idempotent (client ids derive from the segment).

  python -m app.demo.seed_captures --property 197 --coverage 0.85 --stale 0.08 --gap 0.01
  python -m app.demo.seed_captures --purge
"""
import argparse
import json
import random
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core.config import load_config
from app.core.db import SessionLocal
from app.models import Property
from app.schemas.studies import LaneObservations
from app.services.snapshots import active_snapshot
from app.services.studies import catchment_segments, time_band

NS = uuid.UUID("5a1f0c2e-8d7b-4c0e-9a51-5e5d0a7f3b10")
MAIN = {"trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link", "tertiary", "tertiary_link"}


def observations(rng: random.Random, highway: str) -> dict:
    main = highway in MAIN
    obs = {
        "pedestrians_counted": rng.randint(30, 150) if main else rng.randint(4, 40),
        "count_minutes": 5,
        "residential_units": rng.randint(5, 30) if main else rng.randint(10, 60),
        "businesses": rng.randint(5, 25) if main else rng.randint(0, 5),
        "grocery_food_stores": rng.randint(0, 4) if main else rng.choice([0, 0, 0, 1]),
        "anchors": ([{"type": rng.choice(["school", "hospital", "transit", "office", "market", "temple"])}]
                    if rng.random() < 0.05 else []),
        "road_width_band": rng.choice(["medium", "wide"]) if main else rng.choice(["narrow", "narrow", "medium"]),
        "pedestrian_access": rng.choice(["fair", "good"]),
        "vehicle_access": rng.choice(["good"] if main else ["poor", "fair", "good"]),
        "parking": rng.choice(["none", "limited"]) if main else rng.choice(["none", "limited", "good"]),
    }
    return LaneObservations.model_validate(obs).model_dump()   # same schema real captures use


def seed(property_id: int, coverage: float, stale: float, gap: float, rng_seed: int) -> None:
    fd = load_config()["studies"]["freshness_days"]
    rng = random.Random(rng_seed)
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        p = db.get(Property, property_id)
        if p is None:
            raise SystemExit(f"property {property_id} not found")
        snap = active_snapshot(db)
        segs = catchment_segments(db, snap.id, p.lat, p.lon, load_config()["studies"]["catchment_radius_m"])
        meta = {r.segment_id: r for r in db.execute(text(
            "SELECT segment_id, highway FROM road_segments WHERE snapshot_id = :s AND segment_id = ANY(:ids)"),
            dict(s=snap.id, ids=[s["segment_id"] for s in segs]))}
        surveyor = db.scalar(text("SELECT id FROM users WHERE role = 'survey_executive' ORDER BY id LIMIT 1"))
        rng.shuffle(segs)
        total = sum(s["length_m"] for s in segs)
        acc, rows = 0.0, []
        for s in segs:
            share = acc / total
            kind = ("fresh" if share < coverage else "stale" if share < coverage + stale
                    else "gap" if share < coverage + stale + gap else None)
            acc += s["length_m"]
            if kind is None:
                continue
            days = rng.uniform(8, fd - 10) if kind != "stale" else rng.uniform(fd + 10, fd + 120)
            at = (now - timedelta(days=days)).replace(hour=rng.choice([1, 2, 3, 4, 5, 10, 11, 12, 13]))  # 06:30–18:30 IST
            rows.append(dict(client_id=str(uuid.uuid5(NS, f"{s['segment_id']}")), snap=snap.id, seg=s["segment_id"],
                             by=surveyor, status="could_not_survey" if kind == "gap" else "surveyed",
                             reason="gated lane, no access" if kind == "gap" else None, at=at, band=time_band(at),
                             obs=json.dumps(observations(rng, meta[s["segment_id"]].highway)) if kind != "gap" else "{}"))
        n = 0
        for r in rows:
            n += db.execute(text("""
                INSERT INTO segment_captures (client_id, snapshot_id, segment_id, geom, captured_by, source, status,
                                              reason, captured_at, time_band, observations, notes)
                SELECT :client_id, :snap, r.segment_id, r.geom, :by, 'demo_seed', :status, :reason, :at, :band,
                       CAST(:obs AS jsonb), 'demo seed (synthetic, mock provenance)'
                FROM road_segments r WHERE r.snapshot_id = :snap AND r.segment_id = :seg
                ON CONFLICT (client_id) DO NOTHING"""), r).rowcount
        db.commit()
        print(f"property {p.id} '{p.label}': {len(segs)} catchment segments, {len(rows)} seeded, {n} new "
              f"(target fresh {coverage:.0%}, stale {stale:.0%}, could-not-survey {gap:.0%} of length)")


def purge() -> None:
    with SessionLocal() as db:
        db.execute(text("SET LOCAL sitescout.purge = 'on'"))
        db.execute(text("UPDATE study_segments SET reused_capture_id = NULL WHERE reused_capture_id IN "
                        "(SELECT id FROM segment_captures WHERE source = 'demo_seed')"))
        n = db.execute(text("DELETE FROM segment_captures WHERE source = 'demo_seed'")).rowcount
        db.commit()
        print(f"removed {n} demo-seed captures")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--property", type=int)
    ap.add_argument("--coverage", type=float, default=0.85)
    ap.add_argument("--stale", type=float, default=0.08)
    ap.add_argument("--gap", type=float, default=0.01)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--purge", action="store_true")
    a = ap.parse_args()
    if a.purge:
        purge()
    elif a.property is None:
        ap.error("--property is required (or --purge)")
    else:
        seed(a.property, a.coverage, a.stale, a.gap, a.seed)
