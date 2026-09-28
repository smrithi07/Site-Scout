"""M1 scoring engine (docs/DESIGN.md §2, §5). Deterministic, explainable, provenance-aware.

- Each factor has a raw value per score cell; it's normalised as a percentile across every
  scoreable cell in the service area, so a score means "compared with the rest of Chennai".
- Missing is never zero: a missing value is excluded and the remaining weights renormalised.
  If more than `max_missing_weight_fraction` of the weight is missing, the result is facts only.
- The report shows raw → normalised → weight → contribution for every factor.
"""
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import mean

import h3
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import load_config

FACTORS = ("demand", "anchors", "competition", "cannibalisation", "accessibility")

FACTOR_META = {
    "demand": {"label": "Demand", "unit": "m² building footprint per cell", "provenance": "proxy",
               "source": "Microsoft ML building footprints (2026-02)",
               "note": "Building footprint as a proxy for households; not a population count."},
    "anchors": {"label": "Footfall anchors", "unit": "weighted anchors within ~350 m", "provenance": "observed",
                "source": "OpenStreetMap", "note": "Transit stops, markets, schools, hospitals, offices."},
    "competition": {"label": "Competition", "unit": "grocery/convenience shops within ~650 m",
                    "provenance": "observed_lower_bound", "source": "OpenStreetMap",
                    "note": "Lower bound: OSM under-tags small kirana shops. Fewer is better."},
    "cannibalisation": {"label": "Distance from Savomart", "unit": "m to nearest operational store",
                        "provenance": "observed", "source": "Savomart Stores API (cached)",
                        "note": "Farther from an existing store is better (less cannibalisation)."},
    "accessibility": {"label": "Accessibility", "unit": "road metres within ~350 m (main roads weighted)",
                      "provenance": "observed", "source": "OpenStreetMap",
                      "note": "Street density, with main roads counted extra."},
}
HIGHER_IS_WORSE = {"competition"}


@dataclass
class CityModel:
    """Citywide raw values and percentile tables for one (snapshot, config version)."""
    snapshot_id: int
    config_version: str
    cells: dict[str, dict]                              # h3 → cell facts (ward, zone, lat, lon, …)
    scoreable: set[str]
    raw: dict[str, dict[str, float | None]]             # factor → h3 → raw (None = missing)
    sorted_values: dict[str, list[float]] = field(default_factory=dict)
    factor_notes: dict[str, str] = field(default_factory=dict)  # e.g. why a factor is missing everywhere
    extras: dict = field(default_factory=dict)  # derived tables other engines cache here (e.g. site demand)

    def normalized(self, factor: str, cell: str) -> float | None:
        v = self.raw[factor].get(cell)
        values = self.sorted_values[factor]
        if v is None or not values:
            return None
        # Mid-rank percentile: ties share a percentile, so a city full of zeros doesn't rank arbitrarily.
        pct = (bisect_left(values, v) + 0.5 * (bisect_right(values, v) - bisect_left(values, v))) / len(values) * 100
        return round(100 - pct if factor in HIGHER_IS_WORSE else pct, 1)


_cache: dict[tuple[int, str], CityModel] = {}


def city_model(db: Session, snapshot_id: int) -> CityModel:
    cfg = load_config()
    key = (snapshot_id, str(cfg["version"]))
    if key not in _cache:
        _cache.clear()  # one live model per process is plenty
        _cache[key] = _build(db, snapshot_id, cfg)
    return _cache[key]


def _build(db: Session, s: int, cfg: dict) -> CityModel:
    sc, res = cfg["scoring"], cfg["grid"]["score_res"]
    rows = db.execute(text("""
        SELECT f.*, c.ward_no, c.zone_no, ST_Y(ST_Centroid(c.geom)) AS lat, ST_X(ST_Centroid(c.geom)) AS lon,
               st.dist_m AS nearest_store_m, st.store_code AS nearest_store
        FROM cell_features f JOIN h3_cells c USING (snapshot_id, h3)
        LEFT JOIN LATERAL (
            SELECT s.store_code, ST_Distance(s.geom::geography, ST_Centroid(c.geom)::geography) AS dist_m
            FROM stores s WHERE s.snapshot_id = :s AND s.is_operational
            ORDER BY s.geom <-> ST_Centroid(c.geom) LIMIT 1) st ON true
        WHERE f.snapshot_id = :s AND c.res = :res"""), dict(s=s, res=res)).mappings().all()
    cells = {r["h3"]: dict(r) for r in rows}
    scoreable = {h for h, r in cells.items() if r["scoreable"]}

    def ring_sum(cell: str, k: int, fn) -> float:
        return sum(fn(cells[n]) for n in h3.grid_disk(cell, k) if n in cells)

    k, aw = sc["neighbourhood_k"], sc["anchor_weights"]
    dm, can = sc["demand_missing_if"], sc["cannibalisation"]
    stores_age = _stores_age_days(db, s)
    notes = {}
    stores_stale = stores_age is None or stores_age > can["stores_max_age_days"]
    if stores_stale:
        notes["cannibalisation"] = (f"Stores cache is {stores_age:.0f} days old (limit {can['stores_max_age_days']}); "
                                    "factor excluded." if stores_age is not None else "No Stores data; factor excluded.")

    raw: dict[str, dict[str, float | None]] = {f: {} for f in FACTORS}
    for h, c in cells.items():
        unmapped = (c["ml_building_count"] < dm["ml_buildings_below"]
                    and c["residential_road_length_m"] >= dm["local_road_m_at_least"])
        raw["demand"][h] = None if unmapped else float(c["ml_building_footprint_m2"])
        raw["anchors"][h] = ring_sum(h, k["anchors"], lambda x: sum(aw[a] * x[f"{a}_count"] for a in aw))
        raw["competition"][h] = ring_sum(h, k["competition"], lambda x: x["competitor_count"])
        raw["cannibalisation"][h] = (None if stores_stale or c["nearest_store_m"] is None
                                     else min(c["nearest_store_m"], can["max_distance_m"]))
        mult = sc["accessibility"]["main_road_multiplier"]
        raw["accessibility"][h] = ring_sum(h, k["accessibility"],
                                           lambda x: x["road_length_m"] + mult * x["main_road_length_m"])

    model = CityModel(s, str(cfg["version"]), cells, scoreable, raw, factor_notes=notes)
    for f in FACTORS:
        model.sorted_values[f] = sorted(v for h, v in raw[f].items() if h in scoreable and v is not None)
    return model


def _stores_age_days(db: Session, s: int) -> float | None:
    fetched = db.execute(text("SELECT max(fetched_at) FROM stores WHERE snapshot_id = :s"), dict(s=s)).scalar()
    return None if fetched is None else (datetime.now(timezone.utc) - fetched).total_seconds() / 86400


def cell_score(model: CityModel, cell: str, weights: dict, max_missing: float) -> tuple[float | None, dict]:
    norms = {f: model.normalized(f, cell) for f in FACTORS}
    avail = {f: w for f, w in weights.items() if norms[f] is not None}
    if not avail or 1 - sum(avail.values()) / sum(weights.values()) > max_missing:
        return None, norms
    return round(sum(w * norms[f] for f, w in avail.items()) / sum(avail.values()), 1), norms


def score_area(model: CityModel, cells: list[str]) -> dict:
    """Area-level result. `status`: scored | facts_only (too much weight missing) |
    insufficient_data (too little of the selection is scoreable land)."""
    sc = load_config()["scoring"]
    weights, total_w = sc["weights"], sum(sc["weights"].values())
    in_grid = [c for c in cells if c in model.cells]
    scoreable = [c for c in in_grid if c in model.scoreable]
    masked = len(in_grid) - len(scoreable)

    base = {"cells_total": len(in_grid), "cells_scoreable": len(scoreable), "cells_masked": masked,
            "config_version": model.config_version, "snapshot_id": model.snapshot_id}
    if len(scoreable) < sc["min_scoreable_cells"] or len(scoreable) < sc["min_scoreable_share"] * len(in_grid):
        return {**base, "status": "insufficient_data", "score": None, "rating": None, "confidence": None,
                "reason": f"Only {len(scoreable)} of {len(in_grid)} cells are scoreable land (the rest is water, "
                          "industrial, airport or empty). No rating is given for this area.",
                "factors": [], "cell_scores": {}}

    factors, avail_w = [], 0.0
    for f in FACTORS:
        vals = [n for c in scoreable if (n := model.normalized(f, c)) is not None]
        raws = [r for c in scoreable if (r := model.raw[f].get(c)) is not None]
        coverage = len(vals) / len(scoreable)
        available = coverage >= sc["factor_min_coverage"]
        meta = FACTOR_META[f]
        entry = {"factor": f, "label": meta["label"], "unit": meta["unit"], "source": meta["source"],
                 "note": model.factor_notes.get(f, meta["note"]),
                 "provenance": meta["provenance"] if available else "missing",
                 "coverage": round(coverage, 2), "weight": weights[f],
                 "raw": round(mean(raws), 1) if available and raws else None,
                 "normalized": round(mean(vals), 1) if available else None}
        if available:
            avail_w += weights[f]
        factors.append(entry)

    missing_fraction = 1 - avail_w / total_w
    for e in factors:
        e["effective_weight"] = round(100 * e["weight"] / avail_w, 1) if e["normalized"] is not None and avail_w else 0.0
        e["contribution"] = round(e["effective_weight"] * e["normalized"] / 100, 1) if e["normalized"] is not None else None

    q = sc["confidence"]["quality"]
    conf_value = sum(e["weight"] * q[e["provenance"]] for e in factors) / total_w
    confidence = ("High" if conf_value >= sc["confidence"]["high"]
                  else "Medium" if conf_value >= sc["confidence"]["medium"] else "Low")
    cell_scores = {c: s for c in scoreable
                   if (s := cell_score(model, c, weights, sc["max_missing_weight_fraction"])[0]) is not None}

    result = {**base, "factors": factors, "missing_weight_fraction": round(missing_fraction, 2),
              "confidence": confidence, "confidence_value": round(conf_value, 2), "cell_scores": cell_scores}
    if missing_fraction > sc["max_missing_weight_fraction"]:
        return {**result, "status": "facts_only", "score": None, "rating": None,
                "reason": f"{missing_fraction:.0%} of the scoring weight has no data here (limit "
                          f"{sc['max_missing_weight_fraction']:.0%}); showing facts only, no rating."}
    score = round(sum(e["contribution"] for e in factors if e["contribution"] is not None), 1)
    rating = next(b["label"] for b in sc["rating_bands"] if score >= b["min"])
    return {**result, "status": "scored", "score": score, "rating": rating, "reason": None}


def hotspots(model: CityModel, area: dict) -> list[dict]:
    """Top-scoring score cells, spread out (no two within `min_separation_k` rings), each with its
    two strongest contributing factors as the 'why scout here'."""
    cfg = load_config()["scoring"]
    weights, hs = cfg["weights"], cfg["hotspots"]
    chosen: list[dict] = []
    blocked: set[str] = set()
    for cell, score in sorted(area["cell_scores"].items(), key=lambda kv: (-kv[1], kv[0])):
        if cell in blocked:
            continue
        norms = {f: model.normalized(f, cell) for f in FACTORS}
        avail = sum(w for f, w in weights.items() if norms[f] is not None)
        contrib = sorted(((weights[f] * n / avail, f) for f, n in norms.items() if n is not None), reverse=True)
        c = model.cells[cell]
        chosen.append({
            "h3": cell, "score": score, "lat": round(c["lat"], 6), "lon": round(c["lon"], 6),
            "ward_no": c["ward_no"],
            "reasons": [{"factor": f, "label": FACTOR_META[f]["label"], "normalized": norms[f],
                         "raw": round(model.raw[f][cell], 1)} for _, f in contrib[:2]],
            "facts": {"ml_buildings": c["ml_building_count"], "competitors_in_cell": c["competitor_count"],
                      "transit_in_cell": c["transit_count"],
                      "nearest_store_m": round(c["nearest_store_m"]) if c["nearest_store_m"] is not None else None},
        })
        blocked |= set(h3.grid_disk(cell, hs["min_separation_k"]))
        if len(chosen) == hs["count"]:
            break
    return chosen
