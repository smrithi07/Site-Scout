"""Phase 6b checkpoint: evaluation is a versioned job (v1 on onboarding, v2 after an edit), the
outcome honours the completeness gate and hard flags, and every pipeline move is BD-Manager-only,
needs a reason, is audited, and is protected by optimistic locking."""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.auth import Role
from app.core.db import engine
from app.jobs.worker import run_once
from tests.conftest import headers, purge_scouting_test_data

BDM, BDE = headers(Role.BD_MANAGER), headers(Role.BD_EXECUTIVE)
CFG = {"queues": ["test"], "heartbeat_seconds": 1, "stale_after_seconds": 30, "max_attempts": 3}
RANGANATHAN_ST = (13.0405, 80.2335)


@pytest.fixture(autouse=True)
def cleanup():
    yield
    purge_scouting_test_data()


def drain() -> None:
    while run_once("w-test", CFG):
        pass


def a_store() -> tuple[float, float]:
    """An operational Savomart store inside the service area, read from the ingested snapshot (the
    store list comes from the git-ignored Stores API file; no location is committed)."""
    with engine.connect() as conn:
        return tuple(conn.execute(text("""
            SELECT ST_Y(s.geom), ST_X(s.geom) FROM stores s JOIN service_areas a USING (snapshot_id)
            WHERE s.snapshot_id = (SELECT max(id) FROM data_snapshots WHERE status = 'ready')
              AND s.is_operational AND ST_Contains(a.geom, s.geom)
            ORDER BY s.store_code LIMIT 1""")).one())


def onboard(client, lat=RANGANATHAN_ST[0], lon=RANGANATHAN_ST[1], **extra) -> dict:
    body = {"client_id": str(uuid.uuid4()), "label": f"TEST shop {uuid.uuid4().hex[:6]}", "lat": lat, "lon": lon,
            "monthly_rent": 145000, "rent_unit": "per_month", "area_sqft": 1100, "frontage_ft": 18,
            "visibility": "good", "road_width_ft": 20, **extra}
    r = client.post("/properties", json=body, headers=BDE)
    assert r.status_code == 201, r.text
    assert r.json()["evaluation_status"] == "pending"      # saved first; evaluation is a job
    drain()
    return client.get(f"/properties/{r.json()['id']}", headers=BDM).json()


# --- evaluation --------------------------------------------------------------------------

def test_onboarding_produces_an_explainable_v1(client):
    p = onboard(client)
    assert p["evaluation_status"] == "current"
    ev = p["evaluation"]
    assert ev["version"] == 1 and ev["trigger"] == "created"
    assert [f["factor"] for f in ev["factors"]] == ["site_demand", "competition", "cannibalisation",
                                                    "rent_affordability", "accessibility", "visibility", "area_opportunity"]
    assert ev["score"] == pytest.approx(sum(f["contribution"] for f in ev["factors"] if f["contribution"]), abs=0.2)
    assert ev["outcome"] in {"Strong Fit", "Consider", "Weak Fit"}
    rent = next(f for f in ev["factors"] if f["factor"] == "rent_affordability")
    assert rent["provenance"] == "mock"                   # the band is illustrative, and says so
    card = p["review"]
    assert card["rent_vs_band"]["position"] == "within band" and len(card["top_risks"]) <= 3


def test_missing_rent_is_needs_info_never_a_guess(client):
    ev = onboard(client, monthly_rent=None, rent_unit=None)["evaluation"]
    assert ev["outcome"] == "Needs Info"
    assert ev["completeness"]["critical_missing"] == ["monthly_rent"]
    rent = next(f for f in ev["factors"] if f["factor"] == "rent_affordability")
    assert rent["provenance"] == "missing" and rent["contribution"] is None   # not scored as zero
    assert ev["risks"][0]["rule_id"] == "R-DATA"


def test_store_next_door_is_a_hard_flag_that_caps_the_outcome(client):
    ev = onboard(client, lat=a_store()[0] + 0.0004, lon=a_store()[1])["evaluation"]   # ~45 m away
    assert [f["code"] for f in ev["hard_flags"]] == ["store_too_close"]
    assert ev["risks"][0]["rule_id"] == "R-CANNIBAL" and ev["risks"][0]["severity"] == "high"
    assert ev["outcome"] != "Strong Fit"
    if ev["score"] >= 50:  # a score that alone would earn a higher band was capped one level
        assert any("capped" in r for r in ev["completeness"]["outcome_reasons"])


def test_a_stale_stores_cache_excludes_cannibalisation_and_says_why(client, monkeypatch):
    """docs/DESIGN.md §9: Stores API down → use the cache, stamp its age, exclude cannibalisation once
    the cache is too old. The hard flag still uses the last known list (a store next door is too
    important to drop because the list is old)."""
    from app.core.db import SessionLocal
    from app.services import scoring, selection

    monkeypatch.setattr(scoring, "_stores_age_days", lambda db, s: 45.0)
    scoring._cache.clear()                                  # rebuild the city model with the old cache
    try:
        with SessionLocal() as db:
            r = selection.resolve(db, selection.Selection(mode="pincode", pincode="600017"))
            area = scoring.score_area(scoring.city_model(db, r["snapshot_id"]), r["score_cells"])
        can = next(f for f in area["factors"] if f["factor"] == "cannibalisation")
        assert can["provenance"] == "missing" and can["normalized"] is None and "45 days old" in can["note"]
        assert area["status"] == "scored"                  # 15% missing is under the facts-only limit
        assert sum(f["effective_weight"] for f in area["factors"]) == pytest.approx(100, abs=0.2)

        ev = onboard(client, lat=a_store()[0] + 0.0004, lon=a_store()[1])["evaluation"]
        can = next(f for f in ev["factors"] if f["factor"] == "cannibalisation")
        assert can["normalized"] is None and "45 days old" in (can.get("note") or "")
        assert [f["code"] for f in ev["hard_flags"]] == ["store_too_close"]
    finally:
        scoring._cache.clear()


def test_edit_creates_v2_and_versions_are_immutable(client):
    p = onboard(client)
    client.patch(f"/properties/{p['id']}", json={"version": p["version"], "changes": {"visibility": "poor"}}, headers=BDE)
    drain()
    after = client.get(f"/properties/{p['id']}", headers=BDM).json()
    assert after["evaluation"]["version"] == 2 and after["evaluation"]["trigger"] == "edited"
    assert "R-VISIBILITY" in {r["rule_id"] for r in after["evaluation"]["risks"]}
    versions = client.get(f"/properties/{p['id']}/evaluations", headers=BDM).json()
    assert [v["version"] for v in versions] == [2, 1]
    with engine.connect() as conn, pytest.raises(DBAPIError, match="immutable"):
        conn.execute(text("UPDATE property_evaluations SET score = 99 WHERE id = :i"), dict(i=versions[1]["id"]))


# --- pipeline ----------------------------------------------------------------------------

def move(client, p, to, reason="looks promising", h=BDM, version=None):
    return client.post(f"/properties/{p['id']}/stage", json={"to": to, "reason": reason,
                                                              "version": p["version"] if version is None else version},
                       headers=h)


def test_only_the_manager_moves_stages_and_every_move_needs_a_reason(client):
    p = onboard(client)
    assert move(client, p, "under_review", h=BDE).status_code == 403
    assert move(client, p, "under_review", reason="").status_code == 422
    moved = move(client, p, "under_review", reason="good frontage, check rent")
    assert moved.status_code == 200 and moved.json()["stage"] == "under_review"
    trail = client.get(f"/properties/{p['id']}/history", headers=BDM).json()
    last = trail[-1]
    assert (last["action"], last["from_state"], last["to_state"], last["reason"], last["actor_role"]) == \
           ("stage_moved", "scouted", "under_review", "good frontage, check rent", "bd_manager")


def test_concurrent_moves_conflict(client):
    p = onboard(client)
    first = move(client, p, "under_review")
    second = move(client, p, "rejected")                  # same stale version
    assert (first.status_code, second.status_code) == (200, 409)


def test_illegal_and_study_moves_are_refused(client):
    p = onboard(client)
    assert move(client, p, "approved").status_code == 409                      # can't skip to approved
    r = move(client, p, "study_requested")
    assert r.status_code == 409 and "Request study" in r.json()["detail"]      # M3 owns study stages


def test_reject_then_reopen(client):
    p = onboard(client)
    rejected = move(client, p, "rejected", reason="rent too high").json()
    reopened = move(client, rejected, "under_review", reason="owner dropped the rent")
    assert reopened.status_code == 200 and reopened.json()["stage"] == "under_review"


def test_follow_up_loop_returns_the_property_to_review(client):
    p = move(client, onboard(client), "under_review").json()
    fu = client.post(f"/properties/{p['id']}/follow-ups", headers=BDM,
                     json={"kind": "photos", "message": "Need a photo of the shopfront", "version": p["version"]})
    assert fu.status_code == 201
    assert client.get(f"/properties/{p['id']}", headers=BDM).json()["stage"] == "needs_follow_up"
    mine = client.get("/follow-ups", headers=BDE).json()
    assert fu.json()["id"] in {f["id"] for f in mine}

    assert client.post(f"/follow-ups/{fu.json()['id']}/respond", json={"response": "done"}, headers=BDM).status_code == 403
    ok = client.post(f"/follow-ups/{fu.json()['id']}/respond", json={"response": "Uploaded two shopfront photos"},
                     headers=BDE)
    assert ok.status_code == 200
    after = client.get(f"/properties/{p['id']}", headers=BDM).json()
    assert after["stage"] == "under_review" and after["notes"][-1]["kind"] == "follow_up"
    last = client.get(f"/properties/{p['id']}/history", headers=BDM).json()[-1]
    assert last["actor_role"] == "bd_executive" and last["details"]["system_transition"] is True


def test_follow_up_needs_an_executive_to_answer_it(client):
    body = {"client_id": str(uuid.uuid4()), "label": "TEST manager-added", "lat": RANGANATHAN_ST[0], "lon": RANGANATHAN_ST[1]}
    p = client.post("/properties", json=body, headers=BDM).json()
    r = client.post(f"/properties/{p['id']}/follow-ups", headers=BDM,
                    json={"kind": "revisit", "message": "please revisit", "version": p["version"]})
    assert r.status_code == 422


def test_manager_gets_the_allowed_next_steps_executive_does_not(client):
    p = onboard(client)
    assert p["pipeline"]["moves"] == ["under_review", "rejected", "on_hold"]     # from the service's rules
    assert p["pipeline"]["follow_up"]["allowed"] is True
    assert "pipeline" not in client.get(f"/properties/{p['id']}", headers=BDE).json()
    rejected = move(client, p, "rejected", reason="rent too high").json()
    assert rejected["pipeline"]["moves"] == ["under_review"]
    assert rejected["pipeline"]["follow_up"]["allowed"] is False
    assert client.get(f"/properties/{p['id']}/history", headers=BDM).json()[-1]["actor_name"]
