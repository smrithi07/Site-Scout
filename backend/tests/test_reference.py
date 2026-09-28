"""Phase 1 checkpoint. Integration tests: they read the active snapshot, so run `make ingest` first."""
from sqlalchemy import text

from app.core.db import engine
from app.services.localities import normalize
from tests.conftest import bd_client

client = bd_client()


def _q(sql: str):
    with engine.connect() as c:
        s = c.execute(text("SELECT max(id) FROM data_snapshots WHERE status = 'ready'")).scalar()
        return c.execute(text(sql), dict(s=s)).all()


def test_normalize_strips_post_office_suffixes():
    assert normalize("Tiruvottiyur West B.O") == "tiruvottiyur west"
    assert normalize("  T. Nagar  SO ") == "t nagar"


def test_search_returns_pincode_ward_zone():
    body = client.get("/localities/search", params={"q": "Kodungaiyur"}).json()
    top = body["candidates"][0]
    assert top["name"] == "Kodungaiyur"
    assert top["pincode"] == "600118" and top["ward_no"] and top["zone_name"] == "Tondiarpet"
    assert top["geometry"]["basis"] == "pincode" and top["geometry"]["approximate"] is True


def test_ambiguous_name_returns_several_candidates_not_a_guess():
    names = {c["pincode"] for c in client.get("/localities/search", params={"q": "Perambur"}).json()["candidates"][:2]}
    assert names == {"600011", "600012"}


def test_exact_match_drops_weak_fuzzy_hits():
    scores = [c["score"] for c in client.get("/localities/search", params={"q": "Perambur"}).json()["candidates"]]
    assert scores[0] == 1.0 and min(scores) >= 0.5


def test_no_exact_match_keeps_loose_floor():
    scores = [c["score"] for c in client.get("/localities/search", params={"q": "Perambr"}).json()["candidates"]]
    assert scores and max(scores) < 1.0


def test_candidates_resolving_to_same_geometry_are_collapsed():
    pins = [c["pincode"] for c in client.get("/localities/search", params={"q": "Velachery"}).json()["candidates"]
            if c["geometry"]["basis"] == "pincode"]
    assert pins.count("600042") == 1


def test_outside_service_area_is_labelled_not_dropped():
    top = client.get("/localities/search", params={"q": "Tambaram"}).json()["candidates"][0]
    assert top["in_service_area"] is False and top["geometry"]["basis"] is None


def test_pincode_parts_are_tagged_by_source():
    feat = client.get("/reference/pincodes/600119").json()
    assert feat["properties"]["geom_source"] == "datameet_2013+voronoi_approx"
    assert {f["properties"]["geom_source"] for f in feat["features"]} == {"datameet_2013", "voronoi_approx"}
    assert client.get("/reference/pincodes/999999").status_code == 404


def test_pincode_parts_do_not_overlap_and_stay_inside_service_area():
    (overlap_km2, outside_km2), = _q("""
        SELECT (SELECT sum(ST_Area(geom::geography)) - ST_Area(ST_Union(geom)::geography)
                FROM pincodes WHERE snapshot_id = :s) / 1e6,
               (SELECT ST_Area(ST_Difference(ST_Union(p.geom), sa.geom)::geography)
                FROM pincodes p JOIN service_areas sa USING (snapshot_id) WHERE p.snapshot_id = :s
                GROUP BY sa.geom) / 1e6""")
    assert overlap_km2 < 0.01 and outside_km2 < 0.01


def test_every_grid_cell_has_ward_and_zone():
    (missing,), = _q("SELECT count(*) FROM h3_cells WHERE snapshot_id = :s AND (ward_no IS NULL OR zone_no IS NULL)")
    assert missing == 0


def test_snapshot_records_sources():
    snap = client.get("/reference/snapshot").json()
    assert {s["key"] for s in snap["sources"]} >= {"wards_2022", "zones_2022", "pincode_directory_bharatpin",
                                                    "pincode_polygons_datameet", "stores_api"}
    assert snap["stats"]["stores_chn"] == 11
