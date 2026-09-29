"""Phase 10a checkpoint: a survey executive captures lanes of their own unit only; captures are
idempotent by client id; could-not-survey needs a reason; time band and GPS distance are stamped
server-side; the latest capture of a lane counts; a unit submits only when every lane is handled."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core.db import engine
from tests.conftest import purge_scouting_test_data
from tests.test_units import SURVEY_EXEC_ID, planned, post, seg_units  # noqa: F401  (planned is a fixture)
from tests.test_studies import BDM, SE, SM

OBS = {"pedestrians_counted": 23, "count_minutes": 5, "residential_units": 30, "businesses": 4,
       "grocery_food_stores": 1, "anchors": [{"type": "school", "name": "TEST school"}], "road_width_band": "medium",
       "pedestrian_access": "good", "vehicle_access": "fair", "parking": "limited"}


@pytest.fixture(autouse=True)
def cleanup():
    purge_scouting_test_data()
    yield
    purge_scouting_test_data()


@pytest.fixture
def assigned(client, planned):  # noqa: F811
    u = planned["units"][0]
    r = post(client, planned, f"/{u['id']}/assign", {"assignee_id": SURVEY_EXEC_ID})
    assert r.status_code == 200
    lanes = [k for k, v in seg_units(client, planned["study"]["id"]).items() if v["unit_id"] == u["id"]]
    return {"plan": r.json(), "unit": u, "lanes": lanes}


def midpoint(segment_id, study_id, offset_deg=0.0):
    with engine.connect() as conn:
        lat, lon = conn.execute(text("""
            SELECT ST_Y(ST_LineInterpolatePoint(r.geom, 0.5)), ST_X(ST_LineInterpolatePoint(r.geom, 0.5))
            FROM road_segments r JOIN studies s ON s.snapshot_id = r.snapshot_id
            WHERE s.id = :s AND r.segment_id = :g"""), dict(s=study_id, g=segment_id)).one()
    return lat + offset_deg, lon


def body(a, lane, **kw):
    lat, lon = midpoint(lane, a["plan"]["study"]["id"], kw.pop("offset", 0.0))
    return {"client_id": str(uuid.uuid4()), "unit_id": a["unit"]["id"], "segment_id": lane, "status": "surveyed",
            "observations": OBS, "lat": lat, "lon": lon, "gps_accuracy_m": 8, "notes": "TEST capture", **kw}


def test_capture_is_saved_stamped_and_idempotent(client, assigned):
    b = body(assigned, assigned["lanes"][0], captured_at=datetime(2026, 9, 29, 3, 30, tzinfo=timezone.utc).isoformat())
    r = client.post("/captures", json=b, headers=SE)
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["time_band"] == "morning" and c["gps_distance_m"] < 5 and c["warnings"] == []   # 09:00 IST
    again = client.post("/captures", json=b, headers=SE)                  # the phone retried
    assert again.status_code == 200 and again.json()["id"] == c["id"] and again.json()["created"] is False
    unit = client.get(f"/units/{assigned['unit']['id']}", headers=SE).json()
    assert (unit["surveyed"], unit["gaps"], unit["status"]) == (1, 0, "in_progress")


def test_only_the_assignee_captures_their_own_lanes(client, assigned):
    lane = assigned["lanes"][0]
    for h in (SM, BDM):                                                    # the Survey Manager cannot capture
        assert client.post("/captures", json=body(assigned, lane), headers=h).status_code == 403
    sid = assigned["plan"]["study"]["id"]
    other = next(k for k, v in seg_units(client, sid).items() if v["unit_id"] not in (None, assigned["unit"]["id"]))
    r = client.post("/captures", json=body(assigned, other), headers=SE)
    assert r.status_code == 422 and "not part of" in r.json()["detail"]


def test_status_rules_and_observation_bounds(client, assigned):
    lane = assigned["lanes"][0]
    assert client.post("/captures", json=body(assigned, lane, observations=None), headers=SE).status_code == 422
    gap = body(assigned, lane, status="could_not_survey", observations=None)
    assert client.post("/captures", json=gap, headers=SE).status_code == 422                  # no reason
    assert client.post("/captures", json={**gap, "reason": "gated lane"}, headers=SE).status_code == 201
    typo = {**OBS, "pedestrians_counted": 99999}
    assert client.post("/captures", json=body(assigned, assigned["lanes"][1], observations=typo), headers=SE).status_code == 422
    unknown = {**OBS, "rating": 5}                                                             # extra field
    assert client.post("/captures", json=body(assigned, assigned["lanes"][1], observations=unknown), headers=SE).status_code == 422


def test_device_time_is_checked(client, assigned):
    lane = assigned["lanes"][0]
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    stale = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    assert client.post("/captures", json=body(assigned, lane, captured_at=future), headers=SE).status_code == 422
    r = client.post("/captures", json=body(assigned, lane, captured_at=stale), headers=SE)
    assert r.status_code == 422 and "older than" in r.json()["detail"]


def test_far_gps_is_flagged_not_refused(client, assigned):
    r = client.post("/captures", json=body(assigned, assigned["lanes"][0], offset=0.003), headers=SE)   # ~330 m
    assert r.status_code == 201 and r.json()["warnings"][0]["code"] == "gps_far"


def test_latest_capture_counts_and_the_unit_submits_when_every_lane_is_handled(client, assigned):
    uid, lanes = assigned["unit"]["id"], assigned["lanes"]
    client.post("/captures", json=body(assigned, lanes[0], status="could_not_survey", observations=None,
                                       reason="gated"), headers=SE)
    r = client.post(f"/units/{uid}/submit", headers=SE)
    assert r.status_code == 409 and f"{len(lanes) - 1} lane(s)" in r.json()["detail"]
    for lane in lanes:                                                     # lane 0 re-captured: now surveyed
        assert client.post("/captures", json=body(assigned, lane), headers=SE).status_code == 201
    unit = client.post(f"/units/{uid}/submit", headers=SE)
    assert unit.status_code == 200 and unit.json()["status"] == "submitted"
    assert (unit.json()["surveyed"], unit.json()["gaps"]) == (len(lanes), 0)
    assert client.post(f"/units/{uid}/submit", headers=SE).status_code == 200            # idempotent
    late = client.post("/captures", json=body(assigned, lanes[0]), headers=SE)
    assert late.status_code == 409 and "submitted" in late.json()["detail"]
    trail = client.get(f"/audit?entity_type=study&entity_id={assigned['plan']['study']['id']}", headers=SM).json()
    assert [e["action"] for e in trail][-2:] == ["lane_recaptured", "unit_submitted"]
    lane0 = client.get(f"/units/{uid}/segments", headers=SE).json()["features"]
    assert next(f for f in lane0 if f["properties"]["segment_id"] == lanes[0])["properties"]["capture"]["status"] == "surveyed"


def test_an_unassigned_unit_cannot_be_captured(client, planned):  # noqa: F811
    u = planned["units"][0]
    lane = next(k for k, v in seg_units(client, planned["study"]["id"]).items() if v["unit_id"] == u["id"])
    assert client.post("/captures", json=body({"plan": planned, "unit": u}, lane), headers=SE).status_code == 403


def test_captures_close_when_the_study_is_cancelled(client, assigned):
    sid = assigned["plan"]["study"]["id"]
    s = client.get(f"/studies/{sid}", headers=BDM).json()
    assert client.post(f"/studies/{sid}/cancel", json={"version": s["version"], "reason": "owner sold"}, headers=BDM).status_code == 200
    r = client.post("/captures", json=body(assigned, assigned["lanes"][0]), headers=SE)
    assert r.status_code == 409 and "cancelled" in r.json()["detail"]
