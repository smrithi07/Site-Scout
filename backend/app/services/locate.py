"""What's at a point: used to prefill the property form and to validate pins (docs/DESIGN.md §6)."""
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import load_config
from app.services.snapshots import active_snapshot


def rent_band(zone_no: int | None) -> dict:
    """Illustrative (mock) ₹/sq ft/month band for a zone — never market data."""
    bands = load_config()["mock_rent_bands"]
    for name, g in bands["groups"].items():
        if zone_no in g["zones"]:
            return {"min": g["band"][0], "max": g["band"][1], "group": name, "provenance": "mock",
                    "label": bands["label"]}
    return {"min": bands["default"][0], "max": bands["default"][1], "group": "default", "provenance": "mock",
            "label": bands["label"]}


def point_context(db: Session, lat: float, lon: float) -> dict:
    snap = active_snapshot(db)
    reject_classes = load_config()["properties"]["reject_in_landuse"]
    row = db.execute(text("""
        WITH p AS (SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) AS g)
        SELECT (SELECT ST_Intersects(sa.geom, p.g) FROM service_areas sa WHERE sa.snapshot_id = :s) AS in_area,
               (SELECT lclass FROM osm_landuse l WHERE l.snapshot_id = :s AND l.lclass = ANY(:rej)
                  AND ST_Intersects(l.geom, p.g) LIMIT 1) AS in_landuse,
               w.ward_no, w.zone_no, z.name AS zone_name,
               (SELECT q.pincode FROM pincodes q WHERE q.snapshot_id = :s AND ST_Intersects(q.geom, p.g) LIMIT 1) AS pincode,
               (SELECT l.name FROM localities l WHERE l.snapshot_id = :s AND l.kind IN ('osm_place', 'post_office')
                  AND l.ward_no IS NOT NULL AND ST_DWithin(l.geom::geography, p.g::geography, 1500)
                ORDER BY l.kind = 'post_office', l.geom <-> p.g LIMIT 1) AS locality,  -- prefer neighbourhood names
               (SELECT c.h3 FROM h3_cells c WHERE c.snapshot_id = :s AND c.res = :res AND ST_Intersects(c.geom, p.g)
                LIMIT 1) AS cell
        FROM p
        LEFT JOIN wards w ON w.snapshot_id = :s AND ST_Intersects(w.geom, p.g)
        LEFT JOIN zones z ON z.snapshot_id = :s AND z.zone_no = w.zone_no"""),
        dict(s=snap.id, lat=lat, lon=lon, rej=reject_classes, res=load_config()["grid"]["score_res"])).mappings().one()
    out = dict(row)
    out["in_service_area"] = bool(out.pop("in_area"))
    out["rent_band"] = rent_band(out["zone_no"])
    out["snapshot_id"] = snap.id
    return out
