"""OSM ingest: clip the pinned Geofabrik extract to the metro box (osmium-tool), read it once with
pyosmium, COPY the results into temp tables, then build the snapshot tables in SQL.

Produces: osm_pois (incl. place names for the locality index), osm_buildings (point + footprint),
osm_landuse (incl. a sea polygon derived from the coastline), road_segments (split at junctions)."""
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import osmium
from sqlalchemy import Connection, text

from app.core.config import load_config
from ingest.sources import RAW, record_source

PROCESSED = Path("/data/processed")


def _clip(cfg: dict) -> Path:
    src = RAW.parent / cfg["extract"]
    bbox = ",".join(str(v) for v in cfg["bbox"])
    out = PROCESSED / f"{src.name.split('.')[0]}_{bbox.replace(',', '_')}.osm.pbf"
    if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
        PROCESSED.mkdir(exist_ok=True)
        subprocess.run(["osmium", "extract", "-b", bbox, "--strategy", "complete_ways", "--overwrite",
                        "-o", str(out), str(src)], check=True, capture_output=True)
    return out


class _TagMatcher:
    """{name: {key: [values] | ["*"]}} → first name whose tags match (config order)."""

    def __init__(self, spec: dict):
        self.spec = spec
        self.keys = {k for rules in spec.values() for k in rules}

    def match(self, tags) -> tuple[str, str] | None:
        for name, rules in self.spec.items():
            for key, values in rules.items():
                v = tags.get(key)
                if v is not None and ("*" in values or v in values):
                    return name, f"{key}={v}"
        return None


def _ref(o) -> str:
    if isinstance(o, osmium.osm.Area):
        return ("w" if o.from_way() else "r") + str(o.orig_id())
    return o.type_str() + str(o.id)


def _levels(v: str | None) -> int | None:
    try:
        return int(float(v)) if v else None
    except ValueError:
        return None


@dataclass
class _Collected:
    pois: list = field(default_factory=list)       # (ref, category, subtype, name, brand, wkb)
    buildings: list = field(default_factory=list)  # (ref, btype, levels, wkb)
    landuse: list = field(default_factory=list)    # (ref, class, tag, name, wkb)
    coast: list = field(default_factory=list)      # (wkb,)
    ways: list = field(default_factory=list)       # (way_id, highway, name, [(node, lon, lat)])
    bad_geometries: int = 0


def _read(path: Path, cfg: dict) -> _Collected:
    pois = _TagMatcher(cfg["poi_categories"])
    landuse = _TagMatcher(cfg["landuse_classes"])
    places = set(cfg["place_types"])
    roads, service_exclude = set(cfg["road_classes"]), set(cfg["service_exclude"])
    wkb = osmium.geom.WKBFactory()
    out = _Collected()

    area_keys = {"building", "place"} | pois.keys | landuse.keys
    fp = (osmium.FileProcessor(path).with_locations()
          .with_areas(osmium.filter.KeyFilter(*area_keys)))
    for o in fp:
        tags = o.tags
        try:
            if o.is_node():
                geom = None
                if (m := pois.match(tags)):
                    geom = wkb.create_point(o)
                    out.pois.append((_ref(o), *m, tags.get("name"), tags.get("brand"), geom))
                if tags.get("place") in places and tags.get("name"):
                    out.pois.append((_ref(o), "place", f"place={tags['place']}", tags["name"], None,
                                     geom or wkb.create_point(o)))
            elif o.is_way():
                hw = tags.get("highway")
                if (hw in roads and tags.get("area") != "yes"
                        and not (hw == "service" and tags.get("service") in service_exclude)):
                    out.ways.append((o.id, hw, tags.get("name"),
                                     [(n.ref, n.lon, n.lat) for n in o.nodes]))
                if tags.get("natural") == "coastline":
                    out.coast.append((wkb.create_linestring(o),))
            elif o.is_area():
                geom = None
                if "building" in tags:
                    geom = wkb.create_multipolygon(o)
                    out.buildings.append((_ref(o), tags["building"], _levels(tags.get("building:levels")), geom))
                if (m := landuse.match(tags)):
                    geom = geom or wkb.create_multipolygon(o)
                    out.landuse.append((_ref(o), *m, tags.get("name"), geom))
                if (m := pois.match(tags)):
                    geom = geom or wkb.create_multipolygon(o)
                    out.pois.append((_ref(o), *m, tags.get("name"), tags.get("brand"), geom))
                if tags.get("place") in places and tags.get("name"):
                    geom = geom or wkb.create_multipolygon(o)
                    out.pois.append((_ref(o), "place", f"place={tags['place']}", tags["name"], None, geom))
        except RuntimeError:  # invalid/unassemblable geometry — count it, don't abort the ingest
            out.bad_geometries += 1
    return out


def _split_ways(ways: list) -> list:
    """Split every road way at junctions: nodes shared with another road way (or revisited by
    the same way). Returns (segment_id, way_id, from_node, to_node, highway, name, EWKT)."""
    uses = Counter(n for _, _, _, nodes in ways for n, _, _ in nodes)
    segments = []
    for way_id, hw, name, nodes in ways:
        piece, idx = [nodes[0]], 0
        for i, node in enumerate(nodes[1:], start=1):
            piece.append(node)
            if i == len(nodes) - 1 or uses[node[0]] > 1:
                coords = [(x, y) for _, x, y in piece]
                if len(set(coords)) >= 2:
                    wkt = "SRID=4326;LINESTRING(" + ", ".join(f"{x} {y}" for x, y in coords) + ")"
                    segments.append((f"{way_id}:{idx}", way_id, piece[0][0], piece[-1][0], hw, name, wkt))
                    idx += 1
                piece = [node]
    return segments


def _copy(conn: Connection, table: str, columns: str, rows: list) -> None:
    raw = conn.connection.driver_connection
    with raw.cursor() as cur, cur.copy(f"COPY {table} ({columns}) FROM STDIN") as copy:
        for row in rows:
            copy.write_row(row)


def load_osm(conn: Connection, s: int) -> dict:
    cfg = load_config()["osm"]
    clip = _clip(cfg)
    data = _read(clip, cfg)
    segments = _split_ways(data.ways)

    conn.execute(text("""
        CREATE TEMP TABLE t_poi (ref text, category text, subtype text, name text, brand text, geom geometry) ON COMMIT DROP;
        CREATE TEMP TABLE t_bld (ref text, btype text, levels int, geom geometry) ON COMMIT DROP;
        CREATE TEMP TABLE t_lu (ref text, lclass text, tag text, name text, geom geometry) ON COMMIT DROP;
        CREATE TEMP TABLE t_coast (geom geometry) ON COMMIT DROP;
        CREATE TEMP TABLE t_seg (segment_id text, way_id bigint, from_node bigint, to_node bigint,
                                 highway text, name text, geom geometry) ON COMMIT DROP;"""))
    _copy(conn, "t_poi", "ref, category, subtype, name, brand, geom", data.pois)
    _copy(conn, "t_bld", "ref, btype, levels, geom", data.buildings)
    _copy(conn, "t_lu", "ref, lclass, tag, name, geom", data.landuse)
    _copy(conn, "t_coast", "geom", data.coast)
    _copy(conn, "t_seg", "segment_id, way_id, from_node, to_node, highway, name, geom", segments)

    p = dict(s=s)
    # Area POIs (a supermarket drawn as a building, a school campus) become an interior point.
    conn.execute(text("""
        INSERT INTO osm_pois (snapshot_id, osm_ref, category, subtype, name, brand, geom)
        SELECT :s, ref, category, subtype, name, brand, ST_PointOnSurface(ST_SetSRID(geom, 4326))
        FROM t_poi"""), p)
    conn.execute(text("""
        INSERT INTO osm_buildings (snapshot_id, osm_ref, btype, levels, footprint_m2, geom)
        SELECT :s, ref, btype, levels, ST_Area(g::geography), ST_PointOnSurface(g)
        FROM (SELECT ref, btype, levels, ST_MakeValid(ST_SetSRID(geom, 4326)) AS g FROM t_bld) b
        WHERE NOT ST_IsEmpty(g)"""), p)
    conn.execute(text("""
        INSERT INTO osm_landuse (snapshot_id, osm_ref, lclass, tag, name, geom)
        SELECT :s, ref, lclass, tag, name, g
        FROM (SELECT ref, lclass, tag, name,
                     ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SetSRID(geom, 4326)), 3)) AS g
              FROM t_lu) l
        WHERE NOT ST_IsEmpty(g)"""), p)
    conn.execute(text("""
        INSERT INTO road_segments (snapshot_id, segment_id, way_id, from_node, to_node, highway, name, length_m, geom)
        SELECT :s, segment_id, way_id, from_node, to_node, highway, name,
               ST_Length(ST_SetSRID(geom, 4326)::geography), ST_SetSRID(geom, 4326)
        FROM t_seg
        WHERE ST_Length(ST_SetSRID(geom, 4326)::geography) >= 1  -- duplicate-node artefacts"""), p)
    sea_km2 = _build_sea(conn, s, cfg["bbox"])
    # Fresh rows have no planner stats yet; without this the next step picks the snapshot_id
    # btree over the spatial index and scans every building per cell (measured: 550s vs ~5s).
    for table in ("osm_pois", "osm_buildings", "osm_landuse", "road_segments"):
        conn.execute(text(f"ANALYZE {table}"))

    record_source(conn, s, "osm_geofabrik_southern_zone", RAW.parent / cfg["extract"], len(data.ways))
    counts = dict(conn.execute(text(
        "SELECT category, count(*) FROM osm_pois WHERE snapshot_id = :s GROUP BY 1"), p).all())
    return {"osm_buildings": len(data.buildings), "osm_landuse_polygons": len(data.landuse),
            "osm_road_ways": len(data.ways),
            "road_segments": conn.execute(text("SELECT count(*) FROM road_segments WHERE snapshot_id = :s"), p).scalar(),
            "sea_km2": sea_km2, "osm_bad_geometries": data.bad_geometries,
            **{f"osm_pois_{k}": v for k, v in sorted(counts.items())}}


def _build_sea(conn: Connection, s: int, bbox: list) -> float:
    """OSM has no sea polygon, only natural=coastline lines. Split the clip box along the merged
    coastline and keep the pieces touching the box's east edge (the Bay of Bengal side)."""
    x0, y0, x1, y1 = bbox
    conn.execute(text("""
        WITH box AS (SELECT ST_MakeEnvelope(:x0, :y0, :x1, :y1, 4326) AS g),
        coast AS (SELECT ST_LineMerge(ST_Union(ST_Intersection(ST_SetSRID(c.geom, 4326), box.g))) AS g
                  FROM t_coast c, box),
        pieces AS (SELECT (ST_Dump(ST_Split(box.g, coast.g))).geom AS g FROM box, coast)
        INSERT INTO osm_landuse (snapshot_id, osm_ref, lclass, tag, name, geom)
        SELECT :s, 'coastline', 'sea', 'derived:natural=coastline', 'Bay of Bengal', ST_Multi(ST_Union(g))
        FROM pieces
        WHERE ST_Intersects(g, ST_SetSRID(ST_MakeLine(ST_MakePoint(:x1, :y0), ST_MakePoint(:x1, :y1)), 4326))
          AND ST_Area(g) < 0.5 * ST_Area(ST_MakeEnvelope(:x0, :y0, :x1, :y1, 4326))
        HAVING count(*) > 0"""), dict(s=s, x0=x0, y0=y0, x1=x1, y1=y1))
    return round(conn.execute(text("""
        SELECT coalesce(sum(ST_Area(geom::geography)), 0) / 1e6 FROM osm_landuse
        WHERE snapshot_id = :s AND lclass = 'sea'"""), dict(s=s)).scalar(), 1)
