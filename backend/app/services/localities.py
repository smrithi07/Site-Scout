"""Locality search against the local index, and how each hit would resolve to a geometry.
Geometry priority (docs/DESIGN.md §5): pincode polygon → ward polygon → point radius (approximate).
Ambiguous names return several candidates with pincode/ward/zone — we never pick one."""
import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import load_config
from app.core.errors import NotFound
from app.services.snapshots import active_snapshot

# Post-office suffixes (B.O / S.O / H.O) are noise for place-name matching.
_SUFFIX = re.compile(r"\b(b\s?o|s\s?o|h\s?o)\b")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

GEOMETRY_LABELS = {
    "datameet_2013": "approximate, 2013–14 boundaries",
    "voronoi_approx": "approximate, estimated from post-office locations",
    "datameet_2013+voronoi_approx": "approximate, 2013–14 boundaries extended from post-office locations",
    "gcc_2022": "GCC 2022 boundary",
    "point_radius": "approximate (radius around a point)",
}


def normalize(name: str) -> str:
    s = _NON_ALNUM.sub(" ", name.lower())
    return " ".join(_SUFFIX.sub(" ", s).split())


def geometry_basis(kind: str, in_area: bool, pin_source: str | None) -> dict:
    if not in_area:
        return {"basis": None, "source": None, "approximate": None, "label": "outside service area"}
    if kind == "zone":
        basis, source = "zone", "gcc_2022"
    elif kind == "ward":
        basis, source = "ward", "gcc_2022"
    elif pin_source:
        basis, source = "pincode", pin_source
    elif kind in ("post_office", "osm_place"):
        basis, source = "ward", "gcc_2022"
    else:
        basis, source = "point_radius", "point_radius"
    return {"basis": basis, "source": source, "approximate": source not in ("gcc_2022",),
            "label": GEOMETRY_LABELS[source]}


def search(db: Session, q: str) -> tuple[int, list[dict]]:
    cfg = load_config()["localities"]
    snap = active_snapshot(db)
    qn = normalize(q)
    if not qn:
        return snap.id, []
    # Over-fetch: candidates that resolve to the same geometry are collapsed below.
    params = dict(s=snap.id, q=qn, min=cfg["min_score"], lim=cfg["max_results"] * 3)
    if re.fullmatch(r"\d{6}", qn):
        where, score = "l.pincode = :q", "CASE l.kind WHEN 'pincode' THEN 1.0 ELSE 0.9 END"
    else:
        where, score = "true", "greatest(similarity(l.name_norm, :q), word_similarity(:q, l.name_norm))"
    rows = db.execute(text(f"""
        SELECT * FROM (
            SELECT l.id, l.name, l.kind, l.pincode, l.ward_no, l.zone_no, z.name AS zone_name,
                   l.ward_no IS NOT NULL OR l.kind = 'zone' AS in_service_area,
                   ST_Y(l.geom) AS lat, ST_X(l.geom) AS lon, p.geom_source AS pin_source,
                   {score} AS score
            FROM localities l
            LEFT JOIN zones z ON z.snapshot_id = l.snapshot_id AND z.zone_no = l.zone_no
            LEFT JOIN (SELECT pincode, string_agg(geom_source, '+' ORDER BY geom_source) AS geom_source
                       FROM pincodes WHERE snapshot_id = :s GROUP BY pincode) p ON p.pincode = l.pincode
            WHERE l.snapshot_id = :s AND {where}) c
        WHERE score >= :min
        ORDER BY score DESC, in_service_area DESC,
                 array_position(ARRAY['zone','ward','pincode','post_office','osm_place'], kind), name
        LIMIT :lim"""), params).mappings().all()
    # With an exact match present, weak fuzzy hits are noise; keep the loose floor only otherwise.
    if rows and rows[0]["score"] >= 1.0:
        rows = [r for r in rows if r["score"] >= cfg["min_score_with_exact_match"]]
    candidates, seen = [], set()
    for r in rows:
        geometry = geometry_basis(r["kind"], r["in_service_area"], r["pin_source"])
        # "Velachery" (pincode) and "Velacheri" (post office) both resolve to pincode 600042's
        # shape — offering both is noise, so keep only the best-scoring one per geometry.
        key = {"pincode": ("pincode", r["pincode"]), "ward": ("ward", r["ward_no"]),
               "zone": ("zone", r["zone_no"]),
               # an out-of-area office adds nothing once its pincode is already listed
               None: ("pincode", r["pincode"])}.get(geometry["basis"], ("id", r["id"]))
        if key in seen:
            continue
        seen.add(key)
        candidates.append({
            **{k: r[k] for k in ("id", "name", "kind", "pincode", "ward_no", "zone_no", "zone_name",
                                 "in_service_area", "lat", "lon")},
            "score": round(float(r["score"]), 3), "geometry": geometry})
    return snap.id, candidates[:cfg["max_results"]]


def pincode_feature(db: Session, pincode: str) -> dict:
    """The pincode's full shape (all parts unioned) plus each part's source, so the map can
    shade the datameet and Voronoi parts differently."""
    snap = active_snapshot(db)
    parts = db.execute(text("""
        SELECT name, geom_source, clipped, ST_AsGeoJSON(geom)::json AS geometry,
               ST_Area(geom::geography) / 1e6 AS area_km2
        FROM pincodes WHERE snapshot_id = :s AND pincode = :p ORDER BY geom_source"""),
        dict(s=snap.id, p=pincode)).mappings().all()
    if not parts:
        raise NotFound(f"No geometry for pincode {pincode} in snapshot {snap.id}")
    source = "+".join(p["geom_source"] for p in parts)
    return {"type": "FeatureCollection", "properties": {
        "pincode": pincode, "name": parts[0]["name"], "geom_source": source, "label": GEOMETRY_LABELS[source],
        "area_km2": round(sum(p["area_km2"] for p in parts), 2), "snapshot_id": snap.id},
        "features": [{"type": "Feature", "geometry": p["geometry"], "properties": {
            "geom_source": p["geom_source"], "label": GEOMETRY_LABELS[p["geom_source"]],
            "clipped": p["clipped"], "area_km2": round(p["area_km2"], 2)}} for p in parts]}
