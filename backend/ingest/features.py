"""Per-cell raw features on the score grid, plus the non-scoreable mask (docs/DESIGN.md §3).
Everything is a count, length or area share — normalisation and weights are Phase 4's job."""
from sqlalchemy import Connection, text

from app.core.config import load_config


def _run(conn: Connection, sql: str, params: dict) -> None:
    """psycopg sends parameterised SQL one statement at a time — split on statement ends."""
    for stmt in sql.split(";\n"):
        if stmt.strip():
            conn.execute(text(stmt), {k: v for k, v in params.items() if f":{k}" in stmt})


def build_cell_features(conn: Connection, s: int) -> dict:
    cfg = load_config()
    osm, mask = cfg["osm"], cfg["mask"]
    p = dict(s=s, res=cfg["grid"]["score_res"], main=osm["main_road_classes"],
             local=osm["local_road_classes"], blocking=mask["blocking_classes"],
             min_block=mask["min_blocking_share"], empty_road=mask["empty_max_local_road_m"])

    _run(conn, """
        CREATE TEMP TABLE t_cell ON COMMIT DROP AS
            SELECT h3, geom, area_km2 * 1e6 AS area_m2 FROM h3_cells WHERE snapshot_id = :s AND res = :res;
        CREATE INDEX ON t_cell USING gist (geom);
        -- Big land-use polygons are subdivided so per-cell intersections stay cheap.
        CREATE TEMP TABLE t_lu ON COMMIT DROP AS
            SELECT lclass, ST_Subdivide(geom, 128) AS geom FROM osm_landuse WHERE snapshot_id = :s;
        CREATE INDEX ON t_lu USING gist (geom);
        CREATE TEMP TABLE t_junction ON COMMIT DROP AS
            SELECT node, (array_agg(pt))[1] AS geom FROM (
                SELECT from_node AS node, ST_StartPoint(geom) AS pt FROM road_segments WHERE snapshot_id = :s
                UNION ALL
                SELECT to_node, ST_EndPoint(geom) FROM road_segments WHERE snapshot_id = :s) e
            GROUP BY node HAVING count(*) >= 3;
        CREATE INDEX ON t_junction USING gist (geom);
        -- Temp tables get no autovacuum stats; without them the planner nested-loops every cell
        -- against every land-use piece (measured: 571s vs seconds).
        ANALYZE t_cell;
        ANALYZE t_lu;
        ANALYZE t_junction""", p)

    # Land-use share per class, overlapping polygons of one class unioned first (no double count).
    _run(conn, """
        CREATE TEMP TABLE t_share ON COMMIT DROP AS
        SELECT c.h3, l.lclass,
               least(1.0, ST_Area(ST_Union(ST_Intersection(c.geom, l.geom))::geography) / c.area_m2) AS share
        FROM t_cell c JOIN t_lu l ON ST_Intersects(c.geom, l.geom)
        GROUP BY c.h3, l.lclass, c.area_m2;
        CREATE TEMP TABLE t_block ON COMMIT DROP AS
        SELECT c.h3,
               least(1.0, ST_Area(ST_Union(ST_Intersection(c.geom, l.geom))::geography) / c.area_m2) AS share
        FROM t_cell c JOIN t_lu l ON ST_Intersects(c.geom, l.geom) AND l.lclass = ANY(:blocking)
        GROUP BY c.h3, c.area_m2;
        CREATE INDEX ON t_share (h3, lclass);
        ANALYZE t_share;
        ANALYZE t_block""", p)

    conn.execute(text("""
        INSERT INTO cell_features (
            snapshot_id, h3, building_count, building_footprint_m2, residential_share, commercial_share,
            blocking_share, blocking_class, competitor_count, transit_count, school_count, hospital_count,
            office_count, market_count, road_length_m, main_road_length_m, residential_road_length_m,
            junction_count, scoreable, mask_reason)
        SELECT :s, c.h3, coalesce(b.n, 0), coalesce(b.fp, 0),
               coalesce((SELECT share FROM t_share WHERE h3 = c.h3 AND lclass = 'residential'), 0),
               coalesce((SELECT share FROM t_share WHERE h3 = c.h3 AND lclass = 'commercial'), 0),
               coalesce(bl.share, 0),
               (SELECT lclass FROM t_share WHERE h3 = c.h3 AND lclass = ANY(:blocking) ORDER BY share DESC LIMIT 1),
               coalesce(pp.competitor, 0), coalesce(pp.transit, 0), coalesce(pp.school, 0),
               coalesce(pp.hospital, 0), coalesce(pp.office, 0), coalesce(pp.market, 0),
               coalesce(r.total, 0), coalesce(r.main, 0), coalesce(r.local, 0), coalesce(j.n, 0),
               true, NULL
        FROM t_cell c
        LEFT JOIN t_block bl ON bl.h3 = c.h3
        LEFT JOIN LATERAL (
            SELECT count(*) AS n, sum(footprint_m2) AS fp FROM osm_buildings
            WHERE snapshot_id = :s AND ST_Intersects(c.geom, geom)) b ON true
        LEFT JOIN LATERAL (
            SELECT count(*) FILTER (WHERE category = 'competitor') AS competitor,
                   count(*) FILTER (WHERE category = 'transit') AS transit,
                   count(*) FILTER (WHERE category = 'school') AS school,
                   count(*) FILTER (WHERE category = 'hospital') AS hospital,
                   count(*) FILTER (WHERE category = 'office') AS office,
                   count(*) FILTER (WHERE category = 'market') AS market
            FROM osm_pois WHERE snapshot_id = :s AND ST_Intersects(c.geom, geom)) pp ON true
        LEFT JOIN LATERAL (
            SELECT sum(len) AS total,
                   sum(len) FILTER (WHERE highway = ANY(:main)) AS main,
                   sum(len) FILTER (WHERE highway = ANY(:local)) AS local
            FROM (SELECT highway, ST_Length(ST_Intersection(c.geom, geom)::geography) AS len
                  FROM road_segments WHERE snapshot_id = :s AND ST_Intersects(c.geom, geom)) x) r ON true
        LEFT JOIN LATERAL (
            SELECT count(*) AS n FROM t_junction WHERE ST_Intersects(c.geom, geom)) j ON true"""), p)

    conn.execute(text("""
        UPDATE cell_features SET scoreable = false,
               mask_reason = CASE WHEN blocking_share >= :min_block THEN blocking_class ELSE 'empty' END
        WHERE snapshot_id = :s
          AND (blocking_share >= :min_block
               OR (building_count = 0 AND residential_road_length_m < :empty_road))"""), p)

    total, masked = conn.execute(text("""
        SELECT count(*), count(*) FILTER (WHERE NOT scoreable) FROM cell_features WHERE snapshot_id = :s"""),
        p).one()
    reasons = dict(conn.execute(text("""
        SELECT mask_reason, count(*) FROM cell_features WHERE snapshot_id = :s AND NOT scoreable GROUP BY 1"""),
        p).all())
    return {"cell_features": total, "cells_masked": masked,
            **{f"cells_masked_{k}": v for k, v in sorted(reasons.items())}}
