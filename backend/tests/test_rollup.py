"""Phase 10b checkpoint: captured lanes roll up into a Catchment Summary computed over surveyed
lanes only (numbers checked by hand below), footfall from one time band is flagged, OSM's
competitor count is compared with the survey, anchors are de-duplicated, low coverage gives facts
only, and the whole thing runs as a job that completes the study when the last unit is submitted."""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.config import load_config
from app.core.db import engine
from app.jobs.worker import run_once
from app.services.rollup import aggregate
from tests.conftest import purge_scouting_test_data
from tests.test_capture import OBS, body
from tests.test_studies import BDM, SE, SM
from tests.test_units import SURVEY_EXEC_ID, planned, post, seg_units  # noqa: F401  (planned is a fixture)

CFG = load_config()["studies"]["rollup"]
WORKER = {"queues": ["test"], "heartbeat_seconds": 1, "stale_after_seconds": 30, "max_attempts": 3}


def lane(i, length, obs=None, status="surveyed", band="morning", provenance="observed", x=0.0, y=0.0):
    cap = None if status is None else {"status": status, "obs": obs or {}, "band": band, "at": "2026-09-29T04:00:00+00:00",
                                       "provenance": provenance}
    return {"segment_id": f"s{i}", "length_m": length, "x": x, "y": y, "capture": cap}


def o(**kw):
    return {**OBS, "anchors": [], **kw}


# --- aggregation, by hand ------------------------------------------------------------------

def test_signals_are_computed_over_surveyed_lanes_only():
    data = {"mode": "reuse_and_fill", "osm_competitors": 1, "lanes": [
        lane(1, 100, o(residential_units=10, businesses=2, grocery_food_stores=1, pedestrians_counted=10, count_minutes=5,
                       road_width_band="wide", pedestrian_access="good", vehicle_access="good", parking="good")),
        lane(2, 300, o(residential_units=30, businesses=4, grocery_food_stores=2, pedestrians_counted=5, count_minutes=5,
                       road_width_band="narrow", pedestrian_access="poor", vehicle_access="fair", parking="none"),
             band="evening"),
        lane(3, 100, status="could_not_survey"),          # handled, no data
        lane(4, 100, status=None),                        # not surveyed: never filled in
    ]}
    s = aggregate(data, CFG)
    sig = s["signals"]
    assert s["coverage"]["surveyed_share"] == pytest.approx(400 / 600, abs=1e-3)
    assert sig["residential"]["value"] == pytest.approx(40 / 400 * 100)          # 10 per 100 m
    assert sig["commercial"]["value"] == pytest.approx(6 / 400 * 100)            # 1.5 per 100 m
    # footfall: 120/h on 100 m, 60/h on 300 m → length-weighted 75/h
    assert sig["footfall"]["value"] == pytest.approx((120 * 100 + 60 * 300) / 400)
    assert sig["footfall"]["time_bands"] == {"evening": 0.75, "morning": 0.25} and sig["footfall"]["single_band"] is False
    # accessibility: lane 1 = 1.0, lane 2 = (0 + 0 + 0.5)/3 → (100·1 + 300·1/6)/400 = 37.5
    assert sig["accessibility"]["value"] == pytest.approx(37.5) and sig["accessibility"]["share_poor"] == 0.75
    assert sig["parking"]["value"] == pytest.approx(25.0) and sig["parking"]["share_with_parking"] == 0.25
    # competition: 3 stores on 0.4 km = 7.5/km; ≈4.5 across 0.6 km (estimate); OSM lists 1
    comp = sig["competition"]
    assert comp["value"] == pytest.approx(7.5) and comp["estimated_catchment_count"] == pytest.approx(4.5)
    assert comp["osm_count"] == 1 and "undercounts about 4.5×" in comp["notes"][1]
    assert comp["normalized"] == pytest.approx(100 - 7.5 / 8 * 100, abs=0.1)     # fewer is better
    assert s["confidence"] == "medium" and s["facts_only"] is False             # 67% coverage


def test_single_time_band_footfall_is_flagged_and_lowers_confidence():
    lanes = [lane(i, 100, o(), band="midday") for i in range(9)]
    s = aggregate({"mode": "reuse_and_fill", "osm_competitors": 0, "lanes": lanes}, CFG)
    assert s["signals"]["footfall"]["single_band"] is True
    assert "midday band" in s["signals"]["footfall"]["notes"][0]
    assert s["confidence"] == "medium" and "footfall comes from a single time band" in s["confidence_reasons"]


def test_low_coverage_is_facts_only_and_mock_data_is_named():
    lanes = [lane(1, 100, o(), provenance="mock"), lane(2, 100, o(), provenance="observed")] + \
            [lane(i, 100, status=None) for i in range(3, 10)]
    s = aggregate({"mode": "reuse_and_fill", "osm_competitors": 0, "lanes": lanes}, CFG)
    assert s["facts_only"] is True and s["confidence"] == "low"
    assert all(v["normalized"] is None for v in s["signals"].values())
    assert s["signals"]["residential"]["value"] is not None                     # facts are still reported
    assert s["coverage"]["sources"] == {"observed": 0.5, "observed_reused": 0.0, "mock": 0.5}
    assert s["signals"]["residential"]["provenance"] == "mixed"
    assert any("demo (mock) data" in r for r in s["confidence_reasons"])


def test_anchors_seen_from_two_lanes_count_once():
    school = {"type": "school", "name": "Corporation School"}
    lanes = [lane(1, 100, o(anchors=[school]), x=0, y=0), lane(2, 100, o(anchors=[{"type": "school", "name": None}]), x=60, y=0),
             lane(3, 100, o(anchors=[{"type": "school", "name": "Other School"}]), x=80, y=0),
             lane(4, 100, o(anchors=[{"type": "school", "name": None}]), x=900, y=0)]
    s = aggregate({"mode": "reuse_and_fill", "osm_competitors": 0, "lanes": lanes}, CFG)
    names = sorted((a["name"] or "", a["lanes"]) for a in s["anchors"])
    assert names == [("", 1), ("Corporation School", 2), ("Other School", 1)]


def test_unusable_capture_data_is_left_out_not_crashing():
    lanes = [lane(1, 100, o()), lane(2, 100, {"pedestrians_counted": "lots"})]
    s = aggregate({"mode": "reuse_and_fill", "osm_competitors": 0, "lanes": lanes}, CFG)
    assert s["coverage"]["unusable_lanes"] == 1 and s["coverage"]["surveyed_lanes"] == 1


# --- end to end ----------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def cleanup():
    purge_scouting_test_data()
    yield
    purge_scouting_test_data()


def drain():
    while run_once("w-test", WORKER):
        pass


def assign_all(client, plan):
    for u in plan["units"]:
        plan = post(client, plan, f"/{u['id']}/assign", {"assignee_id": SURVEY_EXEC_ID}).json()
    return plan


def capture_unit(client, plan, u, only=None):
    lanes = [k for k, v in seg_units(client, plan["study"]["id"]).items() if v["unit_id"] == u["id"]]
    for lane_id in lanes[:only]:
        r = client.post("/captures", json=body({"plan": plan, "unit": u}, lane_id), headers=SE)
        assert r.status_code == 201, r.text
    return lanes


def test_last_unit_submitted_rolls_up_and_completes_the_study(client, planned):  # noqa: F811
    plan = assign_all(client, planned)
    sid, pid = plan["study"]["id"], plan["study"]["property_id"]
    for u in plan["units"]:
        capture_unit(client, plan, u)
        assert client.post(f"/units/{u['id']}/submit", headers=SE).status_code == 200
    study = client.get(f"/studies/{sid}", headers=SM).json()
    assert study["rollup_job"]["status"] == "queued" and study["status"] == "in_progress"
    drain()
    study = client.get(f"/studies/{sid}", headers=SM).json()
    assert study["status"] == "complete" and study["summary"]["version"] == 1
    assert client.get(f"/properties/{pid}", headers=BDM).json()["stage"] == "study_complete"
    s = client.get(f"/studies/{sid}/summary", headers=BDM).json()
    assert s["coverage"]["surveyed_share"] > 0.95 and s["facts_only"] is False
    assert s["coverage"]["sources"]["observed"] > 0 and s["coverage"]["sources"]["observed_reused"] > 0
    assert s["signals"]["residential"]["normalized"] is not None
    assert s["trigger"] == "all_units_submitted"
    assert client.get(f"/studies/{sid}/summary", headers=SE).status_code == 403
    late = client.post("/captures", json=body({"plan": plan, "unit": plan["units"][0]},
                                              seg_units(client, sid).popitem()[0]), headers=SE)
    assert late.status_code in (403, 409, 422)                                    # captures are closed
    with pytest.raises(DBAPIError, match="immutable"):
        with engine.begin() as conn:
            conn.execute(text("UPDATE catchment_summaries SET confidence = 'high' WHERE study_id = :s"), dict(s=sid))


def test_closing_early_needs_a_reason_and_a_rerun_is_a_new_version(client, planned):  # noqa: F811
    plan = assign_all(client, planned)
    sid = plan["study"]["id"]
    capture_unit(client, plan, plan["units"][0], only=2)
    v = client.get(f"/studies/{sid}", headers=SM).json()["version"]
    r = client.post(f"/studies/{sid}/rollup", json={"version": v}, headers=SM)
    assert r.status_code == 422 and "not submitted" in r.json()["detail"]
    assert client.post(f"/studies/{sid}/rollup", json={"version": v, "reason": "monsoon"}, headers=BDM).status_code == 403
    assert client.post(f"/studies/{sid}/rollup", json={"version": v, "reason": "monsoon — closing with what we have"},
                       headers=SM).status_code == 202
    drain()
    s1 = client.get(f"/studies/{sid}/summary", headers=SM).json()
    assert s1["trigger"] == "closed_early" and s1["version"] == 1
    v = client.get(f"/studies/{sid}", headers=SM).json()["version"]
    first = client.post(f"/studies/{sid}/rollup", json={"version": v, "reason": "re-run"}, headers=SM)
    v = client.get(f"/studies/{sid}", headers=SM).json()["version"]
    dup = client.post(f"/studies/{sid}/rollup", json={"version": v, "reason": "again"}, headers=SM)
    assert first.status_code == 202 and dup.status_code == 409 and "already running" in dup.json()["detail"]
    drain()
    s2 = client.get(f"/studies/{sid}/summary", headers=SM).json()
    assert (s2["version"], s2["trigger"], s2["versions"]) == (2, "rerun", [2, 1])
    assert client.get(f"/studies/{sid}/summary?version=1", headers=SM).json()["id"] == s1["id"]


def test_reuse_only_rolls_up_straight_after_planning(client):
    from tests import test_studies as st
    p = st.shortlisted(client)
    segs = st.catchment(client, p)
    st.capture([s["segment_id"] for s in segs], days_ago=10)                   # everything fresh
    s = st.request(client, p, mode="reuse_only", reason="all fresh, no need to go out").json()
    r = client.post(f"/studies/{s['id']}/plan", json={"version": s["version"], "mode": "reuse_only"}, headers=SM)
    assert r.status_code == 200 and r.json()["rollup_job"]["status"] == "queued"
    drain()
    summary = client.get(f"/studies/{s['id']}/summary", headers=BDM).json()
    assert summary["trigger"] == "reuse_only" and "reuse only — no new survey" in summary["confidence_reasons"]
    assert client.get(f"/properties/{p['id']}", headers=BDM).json()["stage"] == "study_complete"
