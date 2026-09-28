"""Phase 2 data-quality gate (docs/PHASES.md): measures, on the active snapshot, whether OSM is
good enough to (a) skip Bhuvan for the land-use mask and (b) extend the service area to the
metro fringe. Read-only; prints a report. Re-run after any OSM/config change."""
import json

import h3
from sqlalchemy import Connection, text

from app.core.config import load_config

# Ground truth = OSM's own named polygons for places everyone agrees are not neighbourhoods.
NAMED_NON_SCOREABLE = ["Pallikaranai Marsh", "Chennai International Airport", "Chennai Port",
                       "CPCL Refinery", "Ennore Thermal Power Station", "Manali Fertilizers%",
                       "Marina Beach", "Ennore Creek"]
# A cell with this much local street but almost no buildings is inhabited but under-mapped.
ROADED_M, SPARSE_BUILDINGS = 300, 10
FRINGE_BUFFER_M = 10_000


def _mask_check(conn: Connection, s: int) -> list[dict]:
    rows = []
    for pattern in NAMED_NON_SCOREABLE:
        r = conn.execute(text("""
            SELECT count(*) AS cells, count(*) FILTER (WHERE NOT f.scoreable) AS masked
            FROM osm_landuse l
            JOIN h3_cells c ON c.snapshot_id = :s AND c.res = 9 AND ST_Intersects(l.geom, ST_Centroid(c.geom))
            JOIN cell_features f ON f.snapshot_id = :s AND f.h3 = c.h3
            WHERE l.snapshot_id = :s AND l.name ILIKE :p"""), dict(s=s, p=pattern)).one()
        rows.append({"site": pattern.rstrip("%"), "cells_centred_inside": r.cells, "masked": r.masked})
    return rows


def _coverage(conn: Connection, s: int, cells_sql: str) -> dict:
    """Building-coverage metrics over a set of res-9 cells given as SQL returning (h3, geom)."""
    local = load_config()["osm"]["local_road_classes"]
    r = conn.execute(text(f"""
        WITH cells AS ({cells_sql}),
        m AS (
            SELECT c.h3,
                   (SELECT count(*) FROM osm_buildings b WHERE b.snapshot_id = :s AND ST_Intersects(c.geom, b.geom)) AS bld,
                   (SELECT coalesce(sum(ST_Length(ST_Intersection(c.geom, r.geom)::geography)), 0) FROM road_segments r
                    WHERE r.snapshot_id = :s AND r.highway = ANY(:local) AND ST_Intersects(c.geom, r.geom)) AS local_m
            FROM cells c)
        SELECT count(*) AS cells,
               count(*) FILTER (WHERE local_m >= :roaded) AS roaded,
               count(*) FILTER (WHERE local_m >= :roaded AND bld < :sparse) AS roaded_sparse,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY bld) FILTER (WHERE local_m >= :roaded) AS median_bld_roaded
        FROM m"""), dict(s=s, local=local, roaded=ROADED_M, sparse=SPARSE_BUILDINGS)).one()
    return {"cells": r.cells, "roaded_cells": r.roaded,
            "roaded_but_building_sparse_pct": round(100 * r.roaded_sparse / max(r.roaded, 1), 1),
            "median_buildings_per_roaded_cell": r.median_bld_roaded}


def run(conn: Connection, s: int) -> dict:
    report: dict = {"snapshot_id": s, "mask_named_sites": _mask_check(conn, s)}

    report["gcc_all"] = _coverage(conn, s, f"""
        SELECT c.h3, c.geom FROM h3_cells c JOIN cell_features f USING (snapshot_id, h3)
        WHERE c.snapshot_id = {s} AND c.res = 9 AND f.scoreable""")
    report["gcc_by_zone"] = {}
    for zone_no, name in conn.execute(text("SELECT zone_no, name FROM zones WHERE snapshot_id = :s ORDER BY zone_no"),
                                      dict(s=s)).all():
        report["gcc_by_zone"][name] = _coverage(conn, s, f"""
            SELECT c.h3, c.geom FROM h3_cells c JOIN cell_features f USING (snapshot_id, h3)
            WHERE c.snapshot_id = {s} AND c.res = 9 AND f.scoreable AND c.zone_no = {zone_no}""")

    # Fringe ring: within 10 km of GCC, inside the clip box, not GCC, not sea. Cells are built
    # on the fly (the snapshot grid only covers the service area).
    x0, y0, x1, y1 = load_config()["osm"]["bbox"]
    ring = json.loads(conn.execute(text("""
        SELECT ST_AsGeoJSON(ST_Difference(
                   ST_Intersection(ST_Buffer(sa.geom::geography, :buf)::geometry, ST_MakeEnvelope(:x0, :y0, :x1, :y1, 4326)),
                   ST_Union(sa.geom, coalesce((SELECT ST_Union(geom) FROM osm_landuse
                                              WHERE snapshot_id = :s AND lclass = 'sea'), 'POLYGON EMPTY'::geometry))))
        FROM service_areas sa WHERE sa.snapshot_id = :s"""),
        dict(s=s, buf=FRINGE_BUFFER_M, x0=x0, y0=y0, x1=x1, y1=y1)).scalar())
    conn.execute(text("CREATE TEMP TABLE t_ring (h3 text, geom geometry) ON COMMIT DROP"))
    cells = h3.geo_to_cells(ring, 9)
    conn.execute(text("INSERT INTO t_ring VALUES (:h3, ST_SetSRID(ST_GeomFromText(:wkt), 4326))"),
                 [dict(h3=c, wkt="POLYGON((" + ", ".join(f"{lng} {lat}" for lat, lng in
                                                          list(h3.cell_to_boundary(c)) + [h3.cell_to_boundary(c)[0]]) + "))")
                  for c in cells])
    conn.execute(text("CREATE INDEX ON t_ring USING gist (geom); ANALYZE t_ring"))
    report["fringe_ring_10km"] = _coverage(conn, s, "SELECT h3, geom FROM t_ring")
    report["fringe_near_fringe_stores_2km"] = _coverage(conn, s, f"""
        SELECT DISTINCT r.h3, r.geom FROM t_ring r JOIN stores st ON st.snapshot_id = {s} AND st.zone = 'CHN'
        WHERE ST_DWithin(st.geom::geography, ST_Centroid(r.geom)::geography, 2000)""")

    report["landuse_coverage_gcc_pct"] = round(conn.execute(text("""
        SELECT 100 * ST_Area(ST_Intersection(ST_Union(l.geom), sa.geom)::geography) / ST_Area(sa.geom::geography)
        FROM osm_landuse l, service_areas sa
        WHERE l.snapshot_id = :s AND sa.snapshot_id = :s AND l.lclass <> 'sea' AND ST_Intersects(l.geom, sa.geom)
        GROUP BY sa.geom"""), dict(s=s)).scalar(), 1)
    return report
