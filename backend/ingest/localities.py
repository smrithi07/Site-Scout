"""Builds the local locality index (replaces live geocoding) from post offices, pincodes,
wards and zones. Every entry carries pincode/ward/zone so search results can be disambiguated."""
from sqlalchemy import Connection, text

from app.services.localities import normalize


def build_localities(conn: Connection, s: int) -> dict:
    p = dict(s=s)
    # Post-office areas: one entry per (area, pincode). Offices outside the service area are
    # kept (ward_no NULL) so a search can say "outside service area" instead of "not found".
    conn.execute(text("""
        INSERT INTO localities (snapshot_id, name, name_norm, kind, pincode, ward_no, zone_no, geom)
        SELECT DISTINCT ON (area, pincode) :s, area, '', 'post_office', pincode, ward_no, zone_no, geom
        FROM post_offices WHERE snapshot_id = :s
        ORDER BY area, pincode, in_service_area DESC, office_type"""), p)
    conn.execute(text("""
        INSERT INTO localities (snapshot_id, name, name_norm, kind, pincode, ward_no, zone_no, geom)
        SELECT :s, 'Ward ' || ward_no, '', 'ward', NULL, ward_no, zone_no, ST_PointOnSurface(geom)
        FROM wards WHERE snapshot_id = :s"""), p)
    conn.execute(text("""
        INSERT INTO localities (snapshot_id, name, name_norm, kind, pincode, ward_no, zone_no, geom)
        SELECT :s, name, '', 'zone', NULL, NULL, zone_no, ST_PointOnSurface(geom)
        FROM zones WHERE snapshot_id = :s"""), p)
    conn.execute(text("""
        INSERT INTO localities (snapshot_id, name, name_norm, kind, pincode, ward_no, zone_no, geom)
        SELECT :s, coalesce(q.name, q.pincode), '', 'pincode', q.pincode, w.ward_no, w.zone_no, pt
        FROM (SELECT pincode,
                     -- prefer the datameet name; fall back to the post-office areas
                     (array_agg(name ORDER BY geom_source))[1] AS name,
                     ST_PointOnSurface(ST_Union(geom)) AS pt
              FROM pincodes WHERE snapshot_id = :s GROUP BY pincode) q
        LEFT JOIN wards w ON w.snapshot_id = :s AND ST_Intersects(w.geom, q.pt)"""), p)

    # Wards get the pincode their interior point sits in, as a disambiguation hint. Zones span
    # many pincodes, so they get none.
    conn.execute(text("""
        UPDATE localities l SET pincode = q.pincode FROM pincodes q
        WHERE l.snapshot_id = :s AND q.snapshot_id = :s AND l.kind = 'ward'
          AND ST_Intersects(q.geom, l.geom)"""), p)

    rows = conn.execute(text("SELECT id, name, kind, pincode FROM localities WHERE snapshot_id = :s"), p).all()
    conn.execute(text("UPDATE localities SET name_norm = :n WHERE id = :id"),
                 [dict(id=r.id, n=normalize(r.name) + (f" {r.pincode}" if r.kind == "pincode" else ""))
                  for r in rows])
    counts = dict(conn.execute(text(
        "SELECT kind, count(*) FROM localities WHERE snapshot_id = :s GROUP BY 1"), p).all())
    return {f"localities_{k}": v for k, v in sorted(counts.items())}
