"""Microsoft Global ML Building Footprints → ml_buildings (point + footprint), clipped to the OSM
clip box. Files are line-delimited GeoJSON features, gzipped, one per level-9 quadkey tile."""
import gzip
import json

from sqlalchemy import Connection, text

from app.core.config import load_config
from ingest.osm import _copy
from ingest.sources import RAW, record_source


def load_ml_buildings(conn: Connection, s: int) -> dict:
    cfg = load_config()
    ml, (x0, y0, x1, y1) = cfg["ml_buildings"], cfg["osm"]["bbox"]
    files = sorted((RAW.parent / ml["dir"]).glob("*.csv.gz"))
    if not files:
        raise FileNotFoundError(f"no ML building tiles in /data/{ml['dir']}")

    conn.execute(text("CREATE TEMP TABLE t_ml (confidence float, height float, geom text) ON COMMIT DROP"))
    total = kept = 0
    for path in files:
        rows = []
        with gzip.open(path, "rt") as f:
            for line in f:
                total += 1
                feat = json.loads(line)
                x, y = feat["geometry"]["coordinates"][0][0]  # first vertex: cheap box test
                if x0 <= x <= x1 and y0 <= y <= y1:
                    p = feat["properties"]
                    rows.append((p.get("confidence"), p.get("height"), json.dumps(feat["geometry"])))
        kept += len(rows)
        _copy(conn, "t_ml", "confidence, height, geom", rows)
        record_source(conn, s, f"ms_buildings_{path.stem.split('.')[0]}", path, len(rows))

    conn.execute(text("""
        INSERT INTO ml_buildings (snapshot_id, source, confidence, height_m, footprint_m2, geom)
        SELECT :s, :src, nullif(confidence, -1), nullif(height, -1), ST_Area(g::geography), ST_PointOnSurface(g)
        FROM (SELECT confidence, height, ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(geom), 4326)) AS g FROM t_ml) m
        WHERE NOT ST_IsEmpty(g)"""), dict(s=s, src=ml["source"]))
    conn.execute(text("ANALYZE ml_buildings"))
    return {"ml_buildings_read": total, "ml_buildings_in_box": kept}
