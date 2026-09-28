"""Phase 8a checkpoint: a study turns the catchment into road segments; reuse shows length-weighted
fresh coverage and the oldest reused age; stale data is never reused; non-default modes need a
reason at request (BD Manager) and at planning (Survey Manager, final say); everything is audited
and the Survey Manager never sees commercial fields."""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.auth import Role
from app.core.db import engine
from tests.conftest import headers, purge_scouting_test_data

BDM, BDE, SM, SE = (headers(r) for r in (Role.BD_MANAGER, Role.BD_EXECUTIVE, Role.SURVEY_MANAGER, Role.SURVEY_EXECUTIVE))
RANGANATHAN_ST = (13.0405, 80.2335)


@pytest.fixture(autouse=True)
def cleanup():
    purge_scouting_test_data()
    yield
    purge_scouting_test_data()


def shortlisted(client) -> dict:
    body = {"client_id": str(uuid.uuid4()), "label": f"TEST study shop {uuid.uuid4().hex[:6]}",
            "lat": RANGANATHAN_ST[0], "lon": RANGANATHAN_ST[1], "monthly_rent": 120000, "rent_unit": "per_month",
            "area_sqft": 1000, "owner_name": "Owner Secret", "owner_phone": "9999999999"}
    p = client.post("/properties", json=body, headers=BDE).json()
    for to in ("under_review", "shortlisted"):
        p = client.post(f"/properties/{p['id']}/stage", json={"to": to, "reason": "test", "version": p["version"]},
                        headers=BDM).json()
    return p


def active_snapshot() -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT id FROM data_snapshots WHERE status = 'ready' ORDER BY id DESC LIMIT 1")).scalar()


def capture(segment_ids, days_ago, status="surveyed", snapshot_id=None, shift_deg=0.0) -> None:
    """Insert raw captures on segments of the active snapshot (notes 'TEST' → purged)."""
    snap = active_snapshot()
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO segment_captures (client_id, snapshot_id, segment_id, geom, status, reason, captured_at, notes)
            SELECT gen_random_uuid(), :snap, r.segment_id, ST_Translate(r.geom, :d, 0), CAST(:st AS text),
                   CASE WHEN CAST(:st AS text) = 'could_not_survey' THEN 'gate locked' END,
                   now() - (:days * interval '1 day'), 'TEST capture'
            FROM road_segments r WHERE r.snapshot_id = :active AND r.segment_id = ANY(:ids)"""),
            dict(snap=snapshot_id or snap, d=shift_deg, st=status, days=days_ago, active=snap, ids=list(segment_ids)))


def request(client, p, mode="reuse_and_fill", reason=None, h=BDM):
    return client.post("/studies", json={"property_id": p["id"], "version": p["version"], "mode": mode, "reason": reason},
                       headers=h)


def catchment(client, p) -> list[dict]:
    """(segment_id, length) of the property's catchment, via a throwaway preview + the segments map."""
    s = request(client, p).json()
    feats = client.get(f"/studies/{s['id']}/segments", headers=SM).json()["features"]
    client.post(f"/studies/{s['id']}/cancel", json={"version": s["version"], "reason": "test setup"}, headers=BDM)
    p.update(client.get(f"/properties/{p['id']}", headers=BDM).json())   # cancelling bumped its version
    return [f["properties"] for f in feats]


def test_request_turns_the_catchment_into_segments_and_moves_the_property(client):
    p = shortlisted(client)
    preview = client.get(f"/studies/preview?property_id={p['id']}", headers=BDM).json()
    assert preview["segment_count"] > 100 and preview["reuse"]["coverage_pct"] == 0
    r = request(client, p)
    assert r.status_code == 201, r.text
    s = r.json()
    assert (s["status"], s["segment_count"], s["radius_m"]) == ("requested", preview["segment_count"], 600)
    assert s["survey"]["segments"] == s["segment_count"]          # nothing fresh → survey everything
    assert s["reuse"]["message"] == "0% covered by fresh survey data · 100% requires new survey"
    prop = client.get(f"/properties/{p['id']}", headers=BDM).json()
    assert prop["stage"] == "study_requested"
    last = client.get(f"/properties/{p['id']}/history", headers=BDM).json()[-1]
    assert last["to_state"] == "study_requested" and last["details"]["via"] == "study"
    assert request(client, prop).status_code == 409               # one open study per property


def test_only_the_bd_manager_requests_and_only_from_shortlisted(client):
    p = shortlisted(client)
    for h in (BDE, SM, SE):
        assert request(client, p, h=h).status_code == 403
    scouted = client.post("/properties", headers=BDE, json={"client_id": str(uuid.uuid4()), "label": "TEST scouted",
                                                            "lat": RANGANATHAN_ST[0], "lon": RANGANATHAN_ST[1]}).json()
    r = request(client, scouted)
    assert r.status_code == 409 and "shortlisted" in r.json()["detail"]


def test_reuse_is_length_weighted_and_stale_is_never_reused(client):
    p = shortlisted(client)
    segs = catchment(client, p)
    total = sum(s["length_m"] for s in segs)
    fresh, acc = [], 0.0
    for s in sorted(segs, key=lambda s: s["segment_id"]):
        if acc >= 0.85 * total:
            break
        fresh.append(s["segment_id"]); acc += s["length_m"]
    rest = [s["segment_id"] for s in segs if s["segment_id"] not in fresh]
    capture(fresh[: len(fresh) // 2], days_ago=20)
    capture(fresh[len(fresh) // 2:], days_ago=75)
    capture(rest, days_ago=200)                                   # stale: older than 90 days
    capture(fresh[:3], days_ago=300)                              # an older capture never hides a fresh one

    s = request(client, p).json()
    reuse = s["reuse"]
    assert reuse["coverage_pct"] == pytest.approx(100 * acc / total, abs=0.1)
    assert reuse["meets_threshold"] is True
    assert reuse["counts"]["stale"] == len(rest) and reuse["counts"]["fresh"] == len(fresh)
    assert 74.9 < reuse["oldest_reused_days"] < 75.1
    assert s["survey"]["segments"] == len(rest)                   # default: reuse fresh, survey stale
    states = {f["properties"]["segment_id"]: f["properties"]
              for f in client.get(f"/studies/{s['id']}/segments", headers=SM).json()["features"]}
    assert all(states[i]["reuse_state"] == "stale" and states[i]["to_survey"] for i in rest)


def test_could_not_survey_is_handled_but_not_covered(client):
    p = shortlisted(client)
    segs = catchment(client, p)
    gap = [segs[0]["segment_id"]]
    capture(gap, days_ago=5, status="could_not_survey")
    s = request(client, p).json()
    assert s["reuse"]["counts"]["fresh_gap"] == 1 and s["reuse"]["coverage_pct"] == 0
    assert "could not be surveyed recently" in s["reuse"]["message"]
    assert s["survey"]["segments"] == len(segs) - 1               # not retried until stale


def test_overrides_need_reasons_and_the_survey_manager_has_the_final_say(client):
    p = shortlisted(client)
    segs = catchment(client, p)
    capture([s["segment_id"] for s in segs[: len(segs) // 3]], days_ago=10)   # well under 80 %
    r = request(client, p, mode="reuse_only")
    assert r.status_code == 422 and "below 80%" in r.json()["detail"]
    assert request(client, p, mode="full_survey").status_code == 422          # waiving reuse is an override too
    s = request(client, p, mode="reuse_only", reason="indicative read only, budget is tight").json()
    assert s["survey"]["segments"] == 0 and s["requested_mode"] == "reuse_only"

    plan = lambda mode, reason=None, h=SM, v=None: client.post(  # noqa: E731
        f"/studies/{s['id']}/plan", json={"version": v or s["version"], "mode": mode, "reason": reason}, headers=h)
    assert plan("reuse_and_fill", h=BDM).status_code == 403
    assert plan("reuse_and_fill").status_code == 422                          # changing BD's mode needs a reason
    done = plan("reuse_and_fill", "coverage too thin to reuse only")
    assert done.status_code == 200
    d = done.json()
    assert (d["status"], d["planned_mode"], d["effective_mode"]) == ("planned", "reuse_and_fill", "reuse_and_fill")
    assert d["survey"]["segments"] == len(segs) - len(segs) // 3
    assert plan("full_survey", "x" * 5).status_code == 409                    # stale study version
    trail = client.get(f"/audit?entity_type=study&entity_id={s['id']}", headers=BDM).json()
    assert [(e["action"], e["reason"]) for e in trail] == [
        ("requested", "indicative read only, budget is tight"), ("units_generated", "plan (reuse_and_fill)"),
        ("planned", "coverage too thin to reuse only")]


def test_survey_manager_never_sees_commercial_fields(client):
    p = shortlisted(client)
    s = request(client, p).json()
    for body in (client.get(f"/studies/{s['id']}", headers=SM).json(), client.get("/studies", headers=SM).json()[0]):
        prop = body["property"]
        assert prop["label"] == p["label"]
        assert not {"monthly_rent", "security_deposit", "owner_name", "owner_phone", "area_sqft"} & prop.keys()
    assert "monthly_rent" in client.get(f"/studies/{s['id']}", headers=BDM).json()["property"]
    for h in (BDE, SE):
        assert client.get(f"/studies/{s['id']}", headers=h).status_code == 403
    assert client.get(f"/studies/{s['id']}/segments", headers=BDM).status_code == 403


def test_rejecting_mid_study_cancels_it_and_keeps_the_data(client):
    p = shortlisted(client)
    segs = catchment(client, p)
    capture([segs[0]["segment_id"]], days_ago=3)
    s = request(client, p).json()
    prop = client.get(f"/properties/{p['id']}", headers=BDM).json()
    assert "study_requested" not in prop["pipeline"]["moves"]                  # never a manual move
    r = client.post(f"/properties/{p['id']}/stage", json={"to": "rejected", "reason": "owner sold", "version": prop["version"]},
                    headers=BDM)
    assert r.status_code == 200
    assert client.get(f"/studies/{s['id']}", headers=BDM).json()["status"] == "cancelled"
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM segment_captures WHERE notes LIKE 'TEST%'")).scalar() == 1


def test_cancel_returns_the_property_to_shortlisted(client):
    p = shortlisted(client)
    s = request(client, p).json()
    r = client.post(f"/studies/{s['id']}/cancel", json={"version": s["version"], "reason": "wrong property"}, headers=BDM)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert client.get(f"/properties/{p['id']}", headers=BDM).json()["stage"] == "shortlisted"
    assert request(client, client.get(f"/properties/{p['id']}", headers=BDM).json()).status_code == 201  # can re-request


def test_captures_from_an_older_snapshot_count_only_if_the_segment_is_unchanged(client):
    with engine.connect() as conn:
        older = conn.execute(text("SELECT id FROM data_snapshots WHERE id < :a ORDER BY id DESC LIMIT 1"),
                             dict(a=active_snapshot())).scalar()
    if older is None:
        pytest.skip("needs an older data snapshot")
    p = shortlisted(client)
    segs = catchment(client, p)
    same, moved = segs[0]["segment_id"], segs[1]["segment_id"]
    capture([same], days_ago=10, snapshot_id=older)
    capture([moved], days_ago=10, snapshot_id=older, shift_deg=0.001)        # ~110 m away: a different road now
    s = request(client, p).json()
    states = {f["properties"]["segment_id"]: f["properties"]["reuse_state"]
              for f in client.get(f"/studies/{s['id']}/segments", headers=SM).json()["features"]}
    assert (states[same], states[moved]) == ("fresh", "uncovered")


def test_captures_are_append_only(client):
    p = shortlisted(client)
    capture([catchment(client, p)[0]["segment_id"]], days_ago=1)
    with pytest.raises(DBAPIError, match="append-only"):
        with engine.begin() as conn:
            conn.execute(text("UPDATE segment_captures SET status = 'surveyed' WHERE notes LIKE 'TEST%'"))
