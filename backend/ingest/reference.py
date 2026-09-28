"""Reference-data loaders: zones, wards, service area, post offices, pincodes, stores.
Each step takes (conn, snapshot_id) and returns stats for the snapshot record."""
import csv
import json
import re

from sqlalchemy import Connection, text

from app.core.config import load_config
from ingest.kml import placemarks
from ingest.sources import FILES, file_retrieved_at, latest_stores_file, record_source

CLEAN_POLY = "ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Force2D({})), 3))"
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8,
         "IX": 9, "X": 10, "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15}


def assign_nearest_ward(conn: Connection, s: int, table: str, point_sql: str, where: str = "true") -> None:
    """`point_sql` must qualify its columns with `t.` (bare names resolve to `wards`). Tag rows with the ward (and its zone) nearest to `point_sql` — the containing ward for
    points inside one; the adjacent ward for points in a filled sliver or on the border."""
    conn.execute(text(f"""
        UPDATE {table} t SET (ward_no, zone_no) = (
            SELECT ward_no, zone_no FROM wards
            WHERE snapshot_id = :s ORDER BY geom <-> {point_sql} LIMIT 1)
        WHERE t.snapshot_id = :s AND {where}"""), dict(s=s))


def load_zones(conn: Connection, s: int) -> dict:
    n = 0
    for attrs, _, wkt in placemarks(FILES["zones_2022"]):
        if not attrs.get("ZONE"):
            continue  # the file has one attribute-less placemark
        roman = re.sub(r"^ZONE\s*-\s*", "", attrs["ZONE"].strip().upper())
        conn.execute(
            text(f"""INSERT INTO zones (snapshot_id, zone_no, name, region, geom)
                     VALUES (:s, :no, :name, :region, {CLEAN_POLY.format("ST_GeomFromText(:wkt, 4326)")})"""),
            dict(s=s, no=ROMAN[roman], name=attrs["ZONE_NAME"].title(), region=attrs.get("Region"), wkt=wkt),
        )
        n += 1
    record_source(conn, s, "zones_2022", FILES["zones_2022"], n)
    return {"zones": n}


def load_wards(conn: Connection, s: int) -> dict:
    n = 0
    for _, name, wkt in placemarks(FILES["wards_2022"]):
        conn.execute(
            text(f"""INSERT INTO wards (snapshot_id, ward_no, geom)
                     VALUES (:s, :no, {CLEAN_POLY.format("ST_GeomFromText(:wkt, 4326)")})"""),
            dict(s=s, no=int(name), wkt=wkt),
        )
        n += 1
    # The ward file carries no zone; assign each ward to the zone it overlaps most.
    conn.execute(text("""
        UPDATE wards w SET zone_no = (
            SELECT z.zone_no FROM zones z
            WHERE z.snapshot_id = :s AND ST_Intersects(z.geom, w.geom)
            ORDER BY ST_Area(ST_Intersection(z.geom, w.geom)) DESC LIMIT 1)
        WHERE w.snapshot_id = :s"""), dict(s=s))
    no_zone = conn.execute(text("SELECT count(*) FROM wards WHERE snapshot_id=:s AND zone_no IS NULL"),
                           dict(s=s)).scalar()
    record_source(conn, s, "wards_2022", FILES["wards_2022"], n)
    return {"wards": n, "wards_without_zone": no_zone}


def build_service_area(conn: Connection, s: int) -> dict:
    """Union of wards. Holes smaller than `region.min_hole_km2` are digitising slivers between
    adjacent ward polygons and get filled; larger holes are real enclaves (e.g. the St. Thomas
    Mount cantonment) and stay out of the service area."""
    min_hole_m2 = load_config()["region"]["min_hole_km2"] * 1e6
    conn.execute(text(f"""
        INSERT INTO service_areas (snapshot_id, name, geom)
        SELECT :s, 'Greater Chennai Corporation (2022 wards)', {CLEAN_POLY.format("ST_Collect(poly)")}
        FROM (
            SELECT ST_MakePolygon(ST_ExteriorRing(p.geom), ARRAY(
                       SELECT ST_ExteriorRing(r.geom) FROM ST_DumpRings(p.geom) r
                       WHERE r.path[1] > 0 AND ST_Area(r.geom::geography) >= :min_hole)) AS poly
            FROM (SELECT (ST_Dump(ST_Union(geom))).geom FROM wards WHERE snapshot_id = :s) p) x"""),
        dict(s=s, min_hole=min_hole_m2))
    km2, holes = conn.execute(text("""
        SELECT ST_Area(geom::geography)/1e6,
               (SELECT count(*) FROM ST_Dump(geom) d, ST_DumpRings(d.geom) r
                WHERE r.path[1] > 0 AND ST_Area(r.geom::geography) >= :min_hole)
        FROM service_areas WHERE snapshot_id=:s"""), dict(s=s, min_hole=min_hole_m2)).one()
    return {"service_area_km2": round(km2, 1), "service_area_enclaves": holes}


def load_post_offices(conn: Connection, s: int) -> dict:
    rows, skipped = [], 0
    with FILES["pincode_directory_bharatpin"].open(newline="") as f:
        for r in csv.DictReader(f):
            if not r["pincode"].startswith("600"):
                continue
            try:
                lat, lon = float(r["latitude"]), float(r["longitude"])
            except ValueError:
                skipped += 1
                continue
            rows.append(dict(
                s=s, pin=r["pincode"], office=r["officename"], area=r["area"] or r["officename"],
                type=r["officetype"] or None, district=r["district"] or None,
                dec=len(r["latitude"].split(".")[-1]) if "." in r["latitude"] else 0, lat=lat, lon=lon))
    conn.execute(text("""
        INSERT INTO post_offices (snapshot_id, pincode, office_name, area, office_type, district,
                                  coord_decimals, in_service_area, geom)
        VALUES (:s, :pin, :office, :area, :type, :district, :dec, false,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))"""), rows)
    conn.execute(text("""
        UPDATE post_offices p SET in_service_area = true
        FROM service_areas sa
        WHERE p.snapshot_id = :s AND sa.snapshot_id = :s AND ST_Intersects(sa.geom, p.geom)"""), dict(s=s))
    assign_nearest_ward(conn, s, "post_offices", "t.geom", "in_service_area")
    inside = conn.execute(text("SELECT count(*) FROM post_offices WHERE snapshot_id=:s AND in_service_area"),
                          dict(s=s)).scalar()
    record_source(conn, s, "pincode_directory_bharatpin", FILES["pincode_directory_bharatpin"], len(rows))
    return {"post_offices": len(rows), "post_offices_in_service_area": inside,
            "post_offices_skipped_no_coords": skipped}


def load_pincodes(conn: Connection, s: int) -> dict:
    """datameet polygons where they exist (clipped to the service area); Voronoi cells from
    post-office points for every other pincode that has an office inside the service area."""
    gj = json.loads(FILES["pincode_polygons_datameet"].read_text())
    conn.execute(text("CREATE TEMP TABLE dm (pin text, name text, geom geometry) ON COMMIT DROP"))
    conn.execute(
        text("INSERT INTO dm VALUES (:pin, :name, ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326))"),
        [dict(pin=str(f["properties"]["pin"]), name=f["properties"].get("area_name"), g=json.dumps(f["geometry"]))
         for f in gj["features"]],
    )
    conn.execute(text(f"""
        INSERT INTO pincodes (snapshot_id, pincode, name, geom_source, clipped, geom)
        SELECT :s, d.pin, d.name, 'datameet_2013',
               ST_Area(src) - ST_Area(ST_Intersection(src, sa.geom)) > 0.01 * ST_Area(src),
               {CLEAN_POLY.format("ST_Intersection(src, sa.geom)")}
        FROM (SELECT pin,
                     string_agg(DISTINCT regexp_replace(initcap(name), '\\s+(So|Ho|Bo)(\\s+Boundary)?$', ''), ' / ') AS name,
                     ST_MakeValid(ST_Union(ST_MakeValid(geom))) AS src
              FROM dm GROUP BY pin) d
        CROSS JOIN service_areas sa
        WHERE sa.snapshot_id = :s AND ST_Intersects(src, sa.geom)"""), dict(s=s))

    # Voronoi over every distinct in-area office location, dissolved per pincode, minus the
    # datameet coverage. This gives (a) whole shapes for pincodes datameet lacks and (b) extension
    # parts for datameet pincodes whose 2013 polygon stops short of the expanded GCC. Each part is
    # its own row tagged `voronoi_approx`, so provenance stays per part. Slivers are dropped.
    conn.execute(text(f"""
        WITH pts AS (
            SELECT geom, min(pincode) AS pincode
            FROM post_offices WHERE snapshot_id = :s AND in_service_area GROUP BY geom),
        sa AS (SELECT geom FROM service_areas WHERE snapshot_id = :s),
        cells AS (
            SELECT (ST_Dump(ST_VoronoiPolygons(ST_Collect(pts.geom), 0, (SELECT geom FROM sa)))).geom AS cell
            FROM pts),
        labelled AS (
            SELECT pts.pincode, cells.cell FROM cells JOIN pts ON ST_Intersects(cells.cell, pts.geom)),
        covered AS (SELECT ST_Union(geom) AS geom FROM pincodes WHERE snapshot_id = :s),
        parts AS (
            SELECT l.pincode, (ST_Dump(ST_Difference(ST_Intersection(ST_Union(l.cell), (SELECT geom FROM sa)),
                                                     (SELECT geom FROM covered)))).geom AS part
            FROM labelled l GROUP BY l.pincode)
        INSERT INTO pincodes (snapshot_id, pincode, name, geom_source, clipped, geom)
        SELECT :s, pincode,
               (SELECT string_agg(DISTINCT area, ' / ') FROM post_offices o
                WHERE o.snapshot_id = :s AND o.pincode = parts.pincode AND o.in_service_area),
               'voronoi_approx', true, {CLEAN_POLY.format("ST_Collect(part)")}
        FROM parts
        WHERE ST_Dimension(part) = 2 AND ST_Area(part::geography) >= :min_part
        GROUP BY pincode"""), dict(s=s, min_part=load_config()["region"]["min_pincode_part_km2"] * 1e6))

    stats = dict(conn.execute(text(
        "SELECT geom_source, count(*) FROM pincodes WHERE snapshot_id=:s GROUP BY 1"), dict(s=s)).all())
    pins = conn.execute(text("""
        SELECT count(DISTINCT pincode),
               count(*) FILTER (WHERE n = 2),
               (SELECT 100 * ST_Area(ST_Union(p.geom)::geography) / ST_Area(sa.geom::geography)
                FROM pincodes p, service_areas sa WHERE p.snapshot_id = :s AND sa.snapshot_id = :s GROUP BY sa.geom)
        FROM (SELECT pincode, count(*) n FROM pincodes WHERE snapshot_id = :s GROUP BY 1) x"""), dict(s=s)).one()
    no_geom = conn.execute(text("""
        SELECT count(DISTINCT pincode) FROM post_offices p WHERE snapshot_id = :s AND in_service_area
        AND NOT EXISTS (SELECT 1 FROM pincodes q WHERE q.snapshot_id = :s AND q.pincode = p.pincode)"""),
        dict(s=s)).scalar()
    record_source(conn, s, "pincode_polygons_datameet", FILES["pincode_polygons_datameet"], len(gj["features"]))
    return {"pincodes": pins[0],
            "pincode_parts_datameet_2013": stats.get("datameet_2013", 0),
            "pincode_parts_voronoi_approx": stats.get("voronoi_approx", 0),
            "pincodes_datameet_extended_by_voronoi": pins[1],
            "service_area_pct_covered_by_pincodes": round(pins[2], 1),
            "in_area_pincodes_without_geometry": no_geom}


def load_stores(conn: Connection, s: int) -> dict:
    path = latest_stores_file()
    stores = json.loads(path.read_text())["data"]
    conn.execute(text("""
        INSERT INTO stores (snapshot_id, store_code, name, address, zone, is_operational, fetched_at, raw, geom)
        VALUES (:s, :code, :name, :address, :zone, :op, :at, CAST(:raw AS jsonb),
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))"""),
        [dict(s=s, code=st["store_code"], name=st["name"], address=st.get("address"), zone=st.get("zone"),
              op=bool(st.get("is_operational")), at=file_retrieved_at(path), raw=json.dumps(st),
              lat=float(st["geocoordinates"]["latitude"]), lon=float(st["geocoordinates"]["longitude"]))
         for st in stores])
    record_source(conn, s, "stores_api", path, len(stores))
    chn = sum(1 for st in stores if st.get("zone") == "CHN")
    return {"stores": len(stores), "stores_chn": chn}
