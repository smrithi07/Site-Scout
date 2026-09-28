"""H3 grid over the service area: res `score_res` cells whose centre lies inside it, plus their
res `select_res` parents. Each cell is tagged with the ward/zone nearest its centre (border
parents' centres can fall just outside GCC)."""
import json

import h3
from sqlalchemy import Connection, text

from app.core.config import load_config
from ingest.reference import assign_nearest_ward


def _wkt(cell: str) -> str:
    ring = [(lng, lat) for lat, lng in h3.cell_to_boundary(cell)]
    ring.append(ring[0])
    return "POLYGON((" + ", ".join(f"{x} {y}" for x, y in ring) + "))"


def build_grid(conn: Connection, s: int) -> dict:
    grid = load_config()["grid"]
    fine_res, coarse_res = grid["score_res"], grid["select_res"]
    sa = json.loads(conn.execute(
        text("SELECT ST_AsGeoJSON(geom) FROM service_areas WHERE snapshot_id = :s"), dict(s=s)).scalar())

    fine = h3.geo_to_cells(sa, fine_res)
    coarse = {h3.cell_to_parent(c, coarse_res) for c in fine}
    rows = [dict(s=s, h3=c, res=fine_res, parent=h3.cell_to_parent(c, coarse_res),
                 km2=h3.cell_area(c, "km^2"), wkt=_wkt(c)) for c in fine]
    rows += [dict(s=s, h3=c, res=coarse_res, parent=None, km2=h3.cell_area(c, "km^2"), wkt=_wkt(c))
             for c in coarse]
    conn.execute(text("""
        INSERT INTO h3_cells (snapshot_id, h3, res, parent_h3, area_km2, geom)
        VALUES (:s, :h3, :res, :parent, :km2, ST_SetSRID(ST_GeomFromText(:wkt), 4326))"""), rows)
    assign_nearest_ward(conn, s, "h3_cells", "ST_Centroid(t.geom)")
    return {f"h3_res{fine_res}_cells": len(fine), f"h3_res{coarse_res}_cells": len(coarse)}
