"""Seed synthetic PAST lane captures around a property, so reuse can be demonstrated before any real
survey exists. Captures come in contiguous past-unit clusters (one field day each), like real
surveys — not scattered lanes, which would make the remaining gaps unrealistically fragmented.
Every row is `source = 'demo_seed'` (provenance: mock) — the UI and the roll-up label it as such. Deterministic (fixed RNG seed) and idempotent (client ids derive from the segment).

  python -m app.demo.seed_captures --property 197 --coverage 0.85 --stale 0.08 --gap 0.01
  python -m app.demo.seed_captures --purge
"""
import argparse
import json
import math
import random
import uuid
from collections import defaultdict, deque
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


def _count(rng: random.Random, per_m: float, length_m: float) -> int:
    """A count for this lane from a rate per metre (Poisson), so density doesn't depend on how the
    road happens to be split into lanes."""
    lam, k, p = per_m * length_m, 0, 1.0
    limit = math.exp(-lam)
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def observations(rng: random.Random, highway: str, length_m: float) -> dict:
    """Plausible for Chennai by road type, as rates × lane length (demo only — mock provenance):
    homes 8–25 per 100 m on residential lanes (4–12 on main roads), businesses 0.5–2 per 100 m
    (4–12 on main roads), grocery/food 1–3 per km (4–8), footfall 40–180/h (240–720/h)."""
    main = highway in MAIN
    L = max(length_m, 5.0)
    hourly = rng.uniform(240, 720) if main else rng.uniform(40, 180)
    obs = {
        "pedestrians_counted": _count(rng, hourly / 12 / 1.0, 1.0),          # 5-minute count
        "count_minutes": 5,
        "residential_units": _count(rng, rng.uniform(4, 12) / 100 if main else rng.uniform(8, 25) / 100, L),
        "businesses": _count(rng, rng.uniform(4, 12) / 100 if main else rng.uniform(0.5, 2) / 100, L),
        "grocery_food_stores": _count(rng, rng.uniform(4, 8) / 1000 if main else rng.uniform(1, 3) / 1000, L),
        "anchors": ([{"type": rng.choice(["school", "hospital", "transit", "office", "market", "temple"])}]
                    if rng.random() < L / 4000 else []),                  # ~1 anchor per 4 km of lane
        "road_width_band": rng.choice(["medium", "wide"]) if main else rng.choice(["narrow", "narrow", "medium"]),
        "pedestrian_access": rng.choice(["fair", "good"]),
        "vehicle_access": rng.choice(["good"] if main else ["poor", "fair", "good"]),
        "parking": rng.choice(["none", "limited"]) if main else rng.choice(["none", "limited", "good"]),
    }
    return LaneObservations.model_validate(obs).model_dump()   # same schema real captures use


def past_units(segs: list[dict], rng: random.Random, target_m: float) -> list[list[dict]]:
    """Cut the catchment into contiguous clusters (~one past survey unit each) by growing over the
    road graph from random starts. Real past surveys cover walks, not scattered lanes — so stale
    and never-surveyed areas come in blocks too."""
    by_node = defaultdict(list)
    for s in segs:
        by_node[s["from_node"]].append(s)
        by_node[s["to_node"]].append(s)
    left = {s["segment_id"]: s for s in segs}
    clusters = []
    while left:
        start = left.pop(rng.choice(sorted(left)))
        cluster, queue, length = [start], deque([start]), start["length_m"]
        while queue and length < target_m:
            cur = queue.popleft()
            for n in (cur["from_node"], cur["to_node"]):
                for nb in by_node[n]:
                    if nb["segment_id"] in left and length < target_m:
                        del left[nb["segment_id"]]
                        cluster.append(nb)
                        queue.append(nb)
                        length += nb["length_m"]
        clusters.append(cluster)
    # Growth leaves remnants (1–2 lanes boxed in by other clusters); a real past plan would have put
    # them in a neighbouring unit, so fold each small cluster into the cluster it touches.
    owner = {}
    for i, c in enumerate(clusters):
        for s in c:
            owner[s["segment_id"]] = i
    for i, c in enumerate(clusters):
        if not c or sum(s["length_m"] for s in c) >= 0.3 * target_m:
            continue
        near = {owner[nb["segment_id"]] for s in c for n in (s["from_node"], s["to_node"])
                for nb in by_node[n] if owner[nb["segment_id"]] != i and clusters[owner[nb["segment_id"]]]}
        if near:
            j = min(near, key=lambda j: sum(s["length_m"] for s in clusters[j]))
            for s in c:
                owner[s["segment_id"]] = j
            clusters[j] += c
            clusters[i] = []
    return [c for c in clusters if c]


def seed(property_id: int, coverage: float, stale: float, gap: float, rng_seed: int, unit_m: float = 2500) -> None:
    fd = load_config()["studies"]["freshness_days"]
    rng = random.Random(rng_seed)
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        p = db.get(Property, property_id)
        if p is None:
            raise SystemExit(f"property {property_id} not found")
        snap = active_snapshot(db)
        ids = [s["segment_id"] for s in catchment_segments(db, snap.id, p.lat, p.lon,
                                                            load_config()["studies"]["catchment_radius_m"])]
        segs = [dict(r) for r in db.execute(text(
            "SELECT segment_id, highway, from_node, to_node, length_m FROM road_segments "
            "WHERE snapshot_id = :s AND segment_id = ANY(:ids)"), dict(s=snap.id, ids=ids)).mappings()]
        surveyor = db.scalar(text("SELECT id FROM users WHERE role = 'survey_executive' ORDER BY id LIMIT 1"))
        clusters = past_units(segs, rng, unit_m)
        rng.shuffle(clusters)
        total = sum(s["length_m"] for s in segs)
        acc, rows = 0.0, []
        for cluster in clusters:
            share = acc / total
            acc += sum(s["length_m"] for s in cluster)
            kind = "fresh" if share < coverage else "stale" if share < coverage + stale else None
            if kind is None:
                continue                                     # never surveyed
            days = rng.uniform(8, fd - 10) if kind == "fresh" else rng.uniform(fd + 10, fd + 120)
            day = now - timedelta(days=days)                 # one past unit = one field day
            for s in cluster:
                at = day.replace(hour=rng.choice([1, 2, 3, 4, 5, 10, 11, 12, 13]), minute=rng.randrange(60))  # 06:30–19:30 IST
                blocked = kind == "fresh" and rng.random() < gap       # a gated lane inside a surveyed walk
                rows.append(dict(client_id=str(uuid.uuid5(NS, f"{s['segment_id']}")), snap=snap.id, seg=s["segment_id"],
                                 by=surveyor, status="could_not_survey" if blocked else "surveyed",
                                 reason="gated lane, no access" if blocked else None, at=at, band=time_band(at),
                                 obs="{}" if blocked else json.dumps(observations(rng, s["highway"], s["length_m"]))))
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
        print(f"property {p.id} '{p.label}': {len(segs)} catchment segments in {len(clusters)} past-unit clusters, "
              f"{len(rows)} seeded, {n} new (target fresh {coverage:.0%}, stale {stale:.0%} of length; "
              f"{gap:.0%} of fresh lanes could not be surveyed)")


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
