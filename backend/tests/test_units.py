"""Phase 8b checkpoint: planning generates balanced units covering every to-survey segment exactly
once; split / merge / move keep that invariant (re-validated on every edit, stale edits 409);
assignment starts the study; a survey executive sees only their own units, with the property as
a label only."""
import pytest
from sqlalchemy import text

from app.core.config import load_config
from app.core.db import engine
from tests import test_studies as st
from tests.conftest import purge_scouting_test_data

BDM, SM, SE, BDE = st.BDM, st.SM, st.SE, st.BDE
SURVEY_EXEC_ID = 4


@pytest.fixture(autouse=True)
def cleanup():
    purge_scouting_test_data()
    yield
    purge_scouting_test_data()


@pytest.fixture
def planned(client):
    """A planned study with ~25% of its catchment left to survey (a few units)."""
    p = st.shortlisted(client)
    segs = st.catchment(client, p)
    st.capture([s["segment_id"] for s in segs[: int(len(segs) * 0.75)]], days_ago=10)
    s = st.request(client, p).json()
    r = client.post(f"/studies/{s['id']}/plan", json={"version": s["version"], "mode": "reuse_and_fill"}, headers=SM)
    assert r.status_code == 200, r.text
    return client.get(f"/studies/{s['id']}/units", headers=SM).json()


def seg_units(client, study_id) -> dict:
    return {f["properties"]["segment_id"]: f["properties"]
            for f in client.get(f"/studies/{study_id}/segments", headers=SM).json()["features"]}


def assert_invariant(client, study_id):
    for props in seg_units(client, study_id).values():
        assert (props["unit_id"] is not None) == props["to_survey"], props


def post(client, plan, path, body, h=SM):
    return client.post(f"/studies/{plan['study']['id']}/units{path}", json={"version": plan["study"]["version"], **body},
                       headers=h)


def test_plan_generates_balanced_units_covering_each_segment_once(client, planned):
    cfg = load_config()["studies"]["units"]
    study, units = planned["study"], planned["units"]
    assert len(units) >= 2 and study["units"]["count"] == len(units)
    assert sum(u["segment_count"] for u in units) == study["survey"]["segments"]
    assert_invariant(client, study["id"])
    for u in units:
        assert cfg["min_unit_minutes"] * 0.75 <= u["minutes"] <= cfg["max_unit_minutes"] * 1.1, u
        assert u["status"] == "draft" and u["assignee_id"] is None


def test_only_the_survey_manager_edits_units(client, planned):
    u = planned["units"][0]
    for h in (BDM, BDE, SE):
        assert post(client, planned, f"/{u['id']}/assign", {"assignee_id": SURVEY_EXEC_ID}, h=h).status_code == 403
    assert client.get(f"/studies/{planned['study']['id']}/units", headers=BDM).status_code == 403
    summary = client.get(f"/studies/{planned['study']['id']}", headers=BDM).json()["units"]   # status only
    assert summary["count"] == len(planned["units"])


def test_move_split_merge_keep_one_segment_one_unit(client, planned):
    sid = planned["study"]["id"]
    a, b = planned["units"][0], planned["units"][1]
    a_segs = [k for k, v in seg_units(client, sid).items() if v["unit_id"] == a["id"]]

    moved = post(client, planned, "/move", {"segment_ids": a_segs[:2], "to_unit_id": b["id"]})
    assert moved.status_code == 200, moved.text
    plan = moved.json()
    counts = {u["id"]: u["segment_count"] for u in plan["units"]}
    assert (counts[a["id"]], counts[b["id"]]) == (a["segment_count"] - 2, b["segment_count"] + 2)
    assert_invariant(client, sid)
    assert post(client, planned, "/move", {"segment_ids": a_segs[2:3], "to_unit_id": b["id"]}).status_code == 409  # stale

    rest = [k for k, v in seg_units(client, sid).items() if v["unit_id"] == a["id"]]
    split = post(client, plan, f"/{a['id']}/split", {"segment_ids": rest[:1]})
    assert split.status_code == 200, split.text
    plan = split.json()
    new = next(u for u in plan["units"] if u["id"] not in {x["id"] for x in planned["units"]})
    assert new["segment_count"] == 1 and len(plan["units"]) == len(planned["units"]) + 1
    assert_invariant(client, sid)

    merged = post(client, plan, "/merge", {"unit_ids": [a["id"], new["id"]]})
    assert merged.status_code == 200, merged.text
    assert len(merged.json()["units"]) == len(planned["units"])
    assert_invariant(client, sid)


def test_edits_refuse_reused_or_foreign_segments_and_bad_splits(client, planned):
    sid = planned["study"]["id"]
    segs = seg_units(client, sid)
    reused = next(k for k, v in segs.items() if not v["to_survey"])
    a = planned["units"][0]
    r = post(client, planned, "/move", {"segment_ids": [reused], "to_unit_id": a["id"]})
    assert r.status_code == 422 and "reused" in r.json()["detail"]
    assert post(client, planned, "/move", {"segment_ids": ["0:0"], "to_unit_id": a["id"]}).status_code == 422
    all_of_a = [k for k, v in segs.items() if v["unit_id"] == a["id"]]
    assert post(client, planned, f"/{a['id']}/split", {"segment_ids": all_of_a}).status_code == 422
    assert post(client, planned, "/move", {"segment_ids": all_of_a[:1], "to_unit_id": 999999}).status_code == 404
    assert_invariant(client, sid)                                   # nothing half-applied


def test_a_corrupted_plan_is_caught_by_the_next_edit(client, planned):
    sid = planned["study"]["id"]
    a, b = planned["units"][0], planned["units"][1]
    victim = next(k for k, v in seg_units(client, sid).items() if v["unit_id"] == b["id"])
    with engine.begin() as conn:                                     # simulate a bug elsewhere
        conn.execute(text("UPDATE study_segments SET unit_id = NULL WHERE study_id = :s AND segment_id = :g"),
                     dict(s=sid, g=victim))
    any_seg = next(k for k, v in seg_units(client, sid).items() if v["unit_id"] == a["id"])
    r = post(client, planned, "/move", {"segment_ids": [any_seg], "to_unit_id": b["id"]})
    assert r.status_code == 422 and "without a unit" in r.json()["detail"]


def test_assignment_starts_the_study_and_the_executive_sees_only_their_units(client, planned):
    sid, u = planned["study"]["id"], planned["units"][0]
    assert post(client, planned, f"/{u['id']}/assign", {"assignee_id": 2}).status_code == 422   # a BD exec
    r = post(client, planned, f"/{u['id']}/assign", {"assignee_id": SURVEY_EXEC_ID})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["study"]["status"] == "in_progress"
    assert client.get(f"/properties/{plan['study']['property_id']}", headers=BDM).json()["stage"] == "study_in_progress"
    assert next(x for x in plan["units"] if x["id"] == u["id"])["assignee_name"] == "Arjun (Survey Executive)"

    mine = client.get("/my/units", headers=SE).json()
    assert [m["id"] for m in mine if m["study_id"] == sid] == [u["id"]]
    assert set(mine[0]["property"]) == {"id", "label"}                               # a label, nothing else
    assert client.get(f"/units/{u['id']}/segments", headers=SE).json()["features"]
    other = planned["units"][1]["id"]
    assert client.get(f"/units/{other}/segments", headers=SE).status_code == 403    # not theirs
    assert client.get(f"/studies/{sid}", headers=SE).status_code == 403
    assert client.get("/my/units", headers=SM).status_code == 403

    # once assigned, the plan is fixed and units can no longer be regenerated
    assert client.post(f"/studies/{sid}/plan", json={"version": plan["study"]["version"], "mode": "full_survey",
                                                    "reason": "more"}, headers=SM).status_code == 409
    assert post(client, plan, "/generate", {"reason": "start over"}).status_code == 409
    # reassign / unassign are audited; unassign is allowed while nothing is captured
    assert post(client, plan, f"/{u['id']}/assign", {"assignee_id": None}).status_code == 200
    trail = client.get(f"/audit?entity_type=study&entity_id={sid}", headers=SM).json()
    assert [e["action"] for e in trail][-3:] == ["started", "unit_assigned", "unit_unassigned"]


def test_regenerate_before_assignment_needs_a_reason(client, planned):
    assert post(client, planned, "/generate", {"reason": ""}).status_code == 422
    r = post(client, planned, "/generate", {"reason": "try again after the reuse check"})
    assert r.status_code == 200 and len(r.json()["units"]) == len(planned["units"])
