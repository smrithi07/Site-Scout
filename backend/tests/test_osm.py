"""Phase 2 checkpoint. Integration tests on the active snapshot — run `make ingest` first."""
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.db import engine
from app.main import app
from ingest import gate
from ingest.osm import _split_ways

client = TestClient(app)


def _one(sql: str):
    with engine.connect() as c:
        s = c.execute(text("SELECT max(id) FROM data_snapshots WHERE status = 'ready'")).scalar()
        return c.execute(text(sql), dict(s=s)).one()


def test_split_ways_cuts_at_shared_nodes_only():
    # Way 1: a-b-c-d, way 2: x-c-y. Node c is shared → way 1 splits at c; way 2 splits at c.
    ways = [(1, "residential", None, [(1, 0, 0), (2, 1, 0), (3, 2, 0), (4, 3, 0)]),
            (2, "residential", None, [(9, 2, -1), (3, 2, 0), (8, 2, 1)])]
    segs = {s[0]: (s[2], s[3]) for s in _split_ways(ways)}
    assert segs == {"1:0": (1, 3), "1:1": (3, 4), "2:0": (9, 3), "2:1": (3, 8)}


def test_segment_ids_unique_and_nondegenerate():
    n, uniq, short = _one("""SELECT count(*), count(DISTINCT segment_id), count(*) FILTER (WHERE length_m < 1)
                             FROM road_segments WHERE snapshot_id = :s""")
    assert n > 100_000 and n == uniq and short == 0


def test_every_score_cell_has_features():
    cells, feats = _one("""SELECT (SELECT count(*) FROM h3_cells WHERE snapshot_id = :s AND res = 9),
                                  (SELECT count(*) FROM cell_features WHERE snapshot_id = :s)""")
    assert cells == feats


def test_mask_catches_named_non_neighbourhoods():
    with engine.connect() as c:
        s = c.execute(text("SELECT max(id) FROM data_snapshots WHERE status = 'ready'")).scalar()
        for site in gate._mask_check(c, s):
            assert site["cells_centred_inside"] > 0, site
            assert site["masked"] / site["cells_centred_inside"] >= 0.85, site


def test_dense_core_stays_scoreable():
    # T Nagar (600017) is the densest retail core in the city — almost none of it may be masked.
    total, masked = _one("""
        SELECT count(*), count(*) FILTER (WHERE NOT f.scoreable)
        FROM cell_features f JOIN h3_cells c USING (snapshot_id, h3)
        JOIN pincodes p ON p.snapshot_id = c.snapshot_id AND p.pincode = '600017'
             AND ST_Intersects(p.geom, ST_Centroid(c.geom))
        WHERE f.snapshot_id = :s""")
    assert total > 20 and masked <= 1


def test_ml_buildings_close_the_osm_mapping_gap():
    # Gate result: OSM left Manali/Thiruvottriyur/Tondiarpet/Sholinganallur 52–95% building-sparse.
    with engine.connect() as c:
        s = c.execute(text("SELECT max(id) FROM data_snapshots WHERE status = 'ready'")).scalar()
        zones = c.execute(text("SELECT zone_no, name FROM zones WHERE snapshot_id = :s"), dict(s=s)).all()
        for zone_no, name in zones:
            cov = gate._coverage(c, s, f"""
                SELECT c.h3, c.geom FROM h3_cells c JOIN cell_features f USING (snapshot_id, h3)
                WHERE c.snapshot_id = {s} AND c.res = 9 AND f.scoreable AND c.zone_no = {zone_no}""", "ml_buildings")
            assert cov["roaded_but_building_sparse_pct"] <= 10, (name, cov)


def test_osm_place_names_are_searchable():
    top = client.get("/localities/search", params={"q": "Abhiramapuram"}).json()["candidates"][0]
    assert top["kind"] == "osm_place" and top["in_service_area"] and top["zone_name"] == "Teynampet"
