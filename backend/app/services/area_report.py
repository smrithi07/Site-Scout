"""Area Fitness Report building blocks: the facts panel (always shown, even with no rating),
saving an immutable report version, and comparing two reports."""
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core import audit
from app.core.config import load_config
from app.core.errors import NotFound
from app.models import AreaReport, User


def gather_facts(db: Session, snapshot_id: int, cells: list[str]) -> dict:
    """Plain counts and names for the selected area — no scoring, just what's there."""
    p = dict(s=snapshot_id, cells=cells, r=load_config()["scoring"]["cannibalisation"]["radius_m"])
    area_cte = """WITH area AS (SELECT ST_Union(geom) AS g, ST_Centroid(ST_Union(geom)) AS c
                               FROM h3_cells WHERE snapshot_id = :s AND h3 = ANY(:cells))"""
    agg = db.execute(text("""
        SELECT sum(ml_building_count) AS ml_buildings, sum(building_count) AS osm_buildings,
               round((sum(road_length_m) / 1000.0)::numeric, 1) AS road_km,
               round((sum(main_road_length_m) / 1000.0)::numeric, 1) AS main_road_km,
               count(*) FILTER (WHERE NOT scoreable) AS masked
        FROM cell_features WHERE snapshot_id = :s AND h3 = ANY(:cells)"""), p).mappings().one()
    masked_by = dict(db.execute(text("""
        SELECT mask_reason, count(*) FROM cell_features
        WHERE snapshot_id = :s AND h3 = ANY(:cells) AND NOT scoreable GROUP BY 1 ORDER BY 2 DESC"""), p).all())
    pois = db.execute(text(f"""{area_cte}
        SELECT o.category, count(*) AS n,
               (array_agg(DISTINCT o.name) FILTER (WHERE o.name IS NOT NULL))[1:8] AS names
        FROM osm_pois o, area WHERE o.snapshot_id = :s AND o.category <> 'place' AND ST_Intersects(area.g, o.geom)
        GROUP BY o.category"""), p).mappings().all()
    stores_inside = db.execute(text(f"""{area_cte}
        SELECT s.store_code, s.name FROM stores s, area
        WHERE s.snapshot_id = :s AND s.is_operational AND ST_Intersects(area.g, s.geom) ORDER BY s.store_code"""),
        p).mappings().all()
    nearest = db.execute(text(f"""{area_cte}
        SELECT s.store_code, s.name, round(ST_Distance(s.geom::geography, area.c::geography)::numeric) AS distance_m,
               (SELECT count(*) FROM stores s2 WHERE s2.snapshot_id = :s AND s2.is_operational
                  AND ST_DWithin(s2.geom::geography, area.c::geography, :r)) AS within_radius
        FROM stores s, area WHERE s.snapshot_id = :s AND s.is_operational
        ORDER BY s.geom <-> area.c LIMIT 1"""), p).mappings().one_or_none()
    admin = db.execute(text(f"""{area_cte}
        SELECT (SELECT array_agg(DISTINCT w.ward_no ORDER BY w.ward_no) FROM wards w
                WHERE w.snapshot_id = :s AND ST_Intersects(w.geom, area.g)
                  AND ST_Area(ST_Intersection(w.geom, area.g)) > 0.05 * ST_Area(w.geom)) AS wards,
               (SELECT array_agg(DISTINCT z.name ORDER BY z.name) FROM zones z
                WHERE z.snapshot_id = :s AND ST_Intersects(z.geom, ST_PointOnSurface(area.g))) AS zones,
               (SELECT array_agg(DISTINCT q.pincode ORDER BY q.pincode) FROM pincodes q
                WHERE q.snapshot_id = :s AND ST_Intersects(q.geom, area.g)
                  AND ST_Area(ST_Intersection(q.geom, area.g)) > 0.1 * ST_Area(area.g)) AS pincodes
        FROM area"""), p).mappings().one()
    as_of = db.execute(text("""
        SELECT (SELECT created_at FROM data_snapshots WHERE id = :s) AS snapshot_built,
               (SELECT max(fetched_at) FROM stores WHERE snapshot_id = :s) AS stores_fetched,
               (SELECT retrieved_at FROM data_sources WHERE snapshot_id = :s AND key = 'osm_geofabrik_southern_zone') AS osm_retrieved"""),
        dict(s=snapshot_id)).mappings().one()

    by_cat = {r["category"]: {"count": r["n"], "examples": r["names"] or []} for r in pois}
    return {
        "ml_buildings": int(agg["ml_buildings"] or 0), "osm_buildings": int(agg["osm_buildings"] or 0),
        "road_km": float(agg["road_km"] or 0), "main_road_km": float(agg["main_road_km"] or 0),
        "masked_cells": int(agg["masked"] or 0), "masked_by": masked_by,
        "competitors": by_cat.get("competitor", {"count": 0, "examples": []}),
        "anchors": {k: by_cat.get(k, {"count": 0, "examples": []})
                    for k in ("transit", "market", "school", "hospital", "office")},
        "savomart_stores_inside": [dict(r) for r in stores_inside],
        "nearest_savomart": {"store_code": nearest["store_code"], "name": nearest["name"],
                             "distance_m": float(nearest["distance_m"]),
                             "within_radius": int(nearest["within_radius"])} if nearest else None,
        "wards": admin["wards"] or [], "zones": admin["zones"] or [], "pincodes": admin["pincodes"] or [],
        "data_as_of": {k: v.isoformat() if v else None for k, v in as_of.items()},
    }


def save_report(db: Session, *, resolved: dict, area: dict, hotspots: list[dict], facts: dict,
                fact_sheet: dict, narrative: dict, narrative_source: str, job_id: int | None,
                actor: User | None, narrative_meta: dict | None = None) -> AreaReport:
    """Insert the next version for this area. The advisory lock serialises concurrent saves of the
    same area so two runs can't both become 'v2'."""
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), dict(k=resolved["area_key"]))
    version = (db.scalar(select(func.max(AreaReport.version)).where(AreaReport.area_key == resolved["area_key"])) or 0) + 1
    report = AreaReport(
        area_key=resolved["area_key"], version=version, label=resolved["label"], selection=resolved["input"],
        resolved={k: resolved[k] for k in ("mode", "basis", "warnings", "non_contiguous", "area_km2", "score_cells")},
        snapshot_id=area["snapshot_id"], config_version=area["config_version"], status=area["status"],
        score=area["score"], rating=area["rating"], confidence=area["confidence"],
        result={"area": {k: v for k, v in area.items() if k != "cell_scores"}, "cell_scores": area["cell_scores"],
                "hotspots": hotspots, "facts": facts, "fact_sheet": fact_sheet,
                "narrative_meta": narrative_meta or {}},
        narrative=narrative, narrative_source=narrative_source, job_id=job_id,
        created_by=actor.id if actor else None, select_cells=resolved["select_cells"],
        geom=text("(SELECT ST_Multi(ST_Union(geom)) FROM h3_cells WHERE snapshot_id = :s AND h3 = ANY(:cells))")
        .bindparams(s=area["snapshot_id"], cells=resolved["score_cells"]),
    )
    db.add(report)
    db.flush()
    audit.record(db, actor=actor, entity_type="area_report", entity_id=report.id, action="created",
                 to_state=area["status"], reason=f"area analysis of {resolved['label']} (v{version})",
                 details={"area_key": resolved["area_key"], "version": version, "score": area["score"],
                          "job_id": job_id, "snapshot_id": area["snapshot_id"], "config_version": area["config_version"]})
    return report


def get_report(db: Session, report_id: int) -> AreaReport:
    report = db.get(AreaReport, report_id)
    if report is None:
        raise NotFound(f"area report {report_id} not found")
    return report


def compare(a: AreaReport, b: AreaReport) -> dict:
    """b relative to a. Flags differences in data snapshot / config, so a score change can be
    read as 'the area changed' vs 'the inputs or rules changed'."""
    fa = {f["factor"]: f for f in a.result["area"]["factors"]}
    fb = {f["factor"]: f for f in b.result["area"]["factors"]}

    def delta(x, y):
        return None if x is None or y is None else round(y - x, 1)

    factors = [{"factor": k, "label": (fb.get(k) or fa.get(k))["label"],
                **{f"{side}_{m}": (src.get(k) or {}).get(m) for side, src in (("a", fa), ("b", fb))
                   for m in ("raw", "normalized", "effective_weight", "contribution", "provenance")},
                "normalized_delta": delta((fa.get(k) or {}).get("normalized"), (fb.get(k) or {}).get("normalized")),
                "contribution_delta": delta((fa.get(k) or {}).get("contribution"), (fb.get(k) or {}).get("contribution"))}
               for k in dict.fromkeys([*fa, *fb])]
    flags = []
    if a.area_key != b.area_key:
        flags.append("different_area")
    if a.snapshot_id != b.snapshot_id:
        flags.append("different_data_snapshot")
    if a.config_version != b.config_version:
        flags.append("different_config")
    return {
        "a": {"id": a.id, "label": a.label, "version": a.version, "created_at": a.created_at, "status": a.status,
              "score": a.score, "rating": a.rating, "confidence": a.confidence,
              "snapshot_id": a.snapshot_id, "config_version": a.config_version},
        "b": {"id": b.id, "label": b.label, "version": b.version, "created_at": b.created_at, "status": b.status,
              "score": b.score, "rating": b.rating, "confidence": b.confidence,
              "snapshot_id": b.snapshot_id, "config_version": b.config_version},
        "score_delta": delta(a.score, b.score), "flags": flags, "factors": factors,
        "facts": {k: {"a": a.result["facts"].get(k), "b": b.result["facts"].get(k)}
                  for k in ("ml_buildings", "osm_buildings", "road_km", "main_road_km", "masked_cells")},
    }
