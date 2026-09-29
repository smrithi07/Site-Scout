"""City-wide opportunity map (bonus, docs/DESIGN.md §11): high-scoring, un-scouted pockets across
the whole service area, without picking an area first. Reuses the M1 engine end to end:

1. Every scoreable score cell (res 9) gets its M1 cell score; a selection cell (res 8) is rated by
   the mean over its scoreable children (too little scoreable land → not rated).
2. Selection cells already scouted (a property, a live scout task, an operational Savomart store)
   are skipped. Cells already covered by an area report are kept but labelled.
3. Pockets grow greedily from the best remaining cell over adjacent cells above the citywide
   `seed_percentile`, up to `max_cells`; a pocket and its ring are then closed to other pockets.
4. Each pocket is scored with `scoring.score_area` over its score cells — exactly what an area
   report on the same cells computes, so "start analysis" reproduces the number.

A live view, not a snapshot: it is recomputed on request (≈ 50 ms) and stamped with the data
snapshot and config version. The immutable record is the area report a manager starts from it."""
from datetime import datetime, timezone
from statistics import mean

import h3
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import load_config
from app.services import scoring, selection, snapshots

CAVEATS = [
    "Desk estimate only: OpenStreetMap, ML building footprints and the Savomart Stores API — nobody has visited.",
    "Competition is an OpenStreetMap lower bound (small kirana shops are under-mapped).",
    "Scores rank cells against the rest of Chennai; run the area analysis before creating a scout task.",
]


def selection_scores(model: scoring.CityModel) -> tuple[dict[str, float], dict[str, list[str]]]:
    """(res-8 cell → mean score of its scoreable children, res-8 cell → all its score cells).
    Cached on the model: it depends only on (snapshot, config)."""
    if "opportunity_cells" not in model.extras:
        cfg, sc = load_config(), load_config()["scoring"]
        oc, res = cfg["opportunities"], cfg["grid"]["select_res"]
        children: dict[str, list[str]] = {}
        for c in model.cells:
            children.setdefault(h3.cell_to_parent(c, res), []).append(c)
        rated = {}
        for parent, kids in children.items():
            scores = [s for c in kids if c in model.scoreable
                      and (s := scoring.cell_score(model, c, sc["weights"], sc["max_missing_weight_fraction"])[0]) is not None]
            if len(scores) >= oc["min_scoreable_children"] and len(scores) >= oc["min_scoreable_share"] * len(kids):
                rated[parent] = round(mean(scores), 1)
        model.extras["opportunity_cells"] = (rated, {p: sorted(k) for p, k in children.items()})
    return model.extras["opportunity_cells"]


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * pct / 100))]


def grow_pockets(rated: dict[str, float], threshold: float, skip: set[str], max_cells: int) -> list[list[str]]:
    """Pure. Greedy, deterministic: seed from the best open cell; add the best adjacent open cell
    above the threshold until `max_cells`; close the pocket and its ring to later pockets."""
    closed: set[str] = set()
    pockets = []
    for seed, score in sorted(rated.items(), key=lambda kv: (-kv[1], kv[0])):
        if score < threshold:
            break
        if seed in closed or seed in skip:
            continue
        pocket = [seed]
        while len(pocket) < max_cells:
            frontier = {n for c in pocket for n in h3.grid_ring(c, 1)
                        if n not in pocket and n not in closed and n not in skip and rated.get(n, -1) >= threshold}
            if not frontier:
                break
            pocket.append(max(frontier, key=lambda n: (rated[n], n)))
        pockets.append(pocket)
        closed |= {n for c in pocket for n in h3.grid_disk(c, 1)}
    return pockets


def scouted_cells(db: Session, snapshot_id: int) -> dict[str, list[str]]:
    """res-8 cell → why it counts as already scouted (property / scout task / Savomart store)."""
    res = load_config()["grid"]["select_res"]
    out: dict[str, list[str]] = {}
    for r in db.execute(text("SELECT id, ST_Y(geom) AS lat, ST_X(geom) AS lon FROM properties WHERE status <> 'merged'")):
        out.setdefault(h3.latlng_to_cell(r.lat, r.lon, res), []).append(f"property #{r.id}")
    for r in db.execute(text("SELECT id, target_cells FROM scout_tasks WHERE status <> 'cancelled'")):
        for c in r.target_cells or []:
            out.setdefault(c, []).append(f"scout task #{r.id}")
    for r in db.execute(text("""SELECT store_code, ST_Y(geom) AS lat, ST_X(geom) AS lon FROM stores
                                WHERE snapshot_id = :s AND is_operational"""), dict(s=snapshot_id)):
        out.setdefault(h3.latlng_to_cell(r.lat, r.lon, res), []).append(f"Savomart {r.store_code}")
    return out


def analysed_cells(db: Session) -> dict[str, dict]:
    """res-8 cell → the latest area report that covered it (a label, not an exclusion)."""
    out: dict[str, dict] = {}
    for r in db.execute(text("SELECT id, label, created_at, select_cells FROM area_reports ORDER BY id")):
        for c in r.select_cells or []:
            out[c] = {"report_id": r.id, "label": r.label, "created_at": r.created_at}
    return out


def _why(area: dict) -> list[dict]:
    top = sorted((f for f in area["factors"] if f["contribution"] is not None), key=lambda f: -f["contribution"])
    return [{"factor": f["factor"], "label": f["label"], "normalized": f["normalized"], "raw": f["raw"], "unit": f["unit"]}
            for f in top[:2]]


def opportunity_map(db: Session) -> dict:
    cfg = load_config()
    oc = cfg["opportunities"]
    s = snapshots.active_snapshot(db).id
    model = scoring.city_model(db, s)
    rated, children = selection_scores(model)
    threshold = percentile(list(rated.values()), oc["seed_percentile"])
    scouted = {c: why for c, why in scouted_cells(db, s).items() if c in children}
    analysed = analysed_cells(db)

    pockets = []
    for cells in grow_pockets(rated, threshold, set(scouted), oc["max_cells"]):
        score_cells = [c for p in cells for c in children[p]]
        area = scoring.score_area(model, score_cells)
        if area["status"] != "scored":
            continue
        facts = [model.cells[c] for c in score_cells]
        near = [f["nearest_store_m"] for f in facts if f["nearest_store_m"] is not None]
        reports = {analysed[c]["report_id"]: analysed[c] for c in cells if c in analysed}
        pockets.append({
            "cells": cells, "score": area["score"], "rating": area["rating"], "confidence": area["confidence"],
            "cell_scores": {c: rated[c] for c in cells},
            "label": selection.nearby_name(db, s, score_cells).removeprefix(" near ") or f"{len(cells)} cells",
            "area_km2": round(sum(h3.cell_area(c, "km^2") for c in cells), 2),
            "why": _why(area),
            "factors": [{k: f[k] for k in ("factor", "label", "provenance", "normalized", "effective_weight", "contribution")}
                        for f in area["factors"]],
            "facts": {"ml_buildings": sum(f["ml_building_count"] for f in facts),
                      "osm_competitors": sum(f["competitor_count"] for f in facts),
                      "transit_stops": sum(f["transit_count"] for f in facts),
                      "nearest_store_m": round(min(near)) if near else None},
            "analysed": sorted(reports.values(), key=lambda r: -r["report_id"]),
            "selection": {"mode": "cells", "cells": cells},
        })
    pockets.sort(key=lambda p: (-p["score"], p["cells"][0]))
    pockets = pockets[:oc["count"]]
    for i, p in enumerate(pockets, 1):
        p["rank"] = i

    return {
        "snapshot_id": s, "config_version": model.config_version, "computed_at": datetime.now(timezone.utc),
        "basis": "desk estimate (proxy)", "caveats": CAVEATS,
        "method": {"seed_percentile": oc["seed_percentile"], "threshold": threshold, "max_cells": oc["max_cells"]},
        "cells_rated": len(rated), "cells_scouted": len(scouted), "cell_scores": rated,
        "scouted": [{"h3": c, "why": why} for c, why in sorted(scouted.items())],
        "pockets": pockets,
    }
