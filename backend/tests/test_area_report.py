"""Phase 4a checkpoint: an area report runs end to end and saves an immutable, versioned snapshot;
re-running creates v2; reports compare; bad selections are rejected with a reason.
Integration tests on the active data snapshot (run `make ingest` first); jobs run on queue 'test'."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.auth import Role
from app.core.db import SessionLocal, engine
from app.core.errors import SelectionError
from app.jobs import queue
from app.jobs.worker import run_once
from app.models import AreaReport, User
from app.services import selection
from tests.conftest import USER_IDS, headers

CFG = {"queues": ["test"], "poll_seconds": 0.1, "heartbeat_seconds": 1, "stale_after_seconds": 30, "max_attempts": 3}
T_NAGAR = {"mode": "pincode", "pincode": "600017"}


@pytest.fixture(autouse=True)
def cleanup():
    yield
    with engine.begin() as conn:  # test data only — the purge switch app code never sets
        conn.execute(text("SET LOCAL sitescout.purge = 'on'"))
        conn.execute(text("DELETE FROM area_reports WHERE job_id IN (SELECT id FROM jobs WHERE queue = 'test')"))
        conn.execute(text("DELETE FROM jobs WHERE queue = 'test'"))


def _run(sel: dict) -> AreaReport:
    with SessionLocal() as db:
        job = queue.enqueue(db, "area_report", {"selection": sel, "actor_id": USER_IDS[Role.BD_MANAGER]},
                            db.get(User, USER_IDS[Role.BD_MANAGER]), queue="test")
        db.commit()
        job_id = job.id
    assert run_once("w-test", CFG) == (job_id, "succeeded")
    with SessionLocal() as db:
        return db.query(AreaReport).filter(AreaReport.job_id == job_id).one()


def _resolve(**sel):
    with SessionLocal() as db:
        return selection.resolve(db, selection.Selection(**sel))


def test_report_end_to_end_and_versioning():
    v1 = _run(T_NAGAR)
    assert v1.status == "scored" and 0 <= v1.score <= 100 and v1.rating and v1.confidence
    assert v1.narrative_source == "template" and v1.narrative["summary"].startswith("Pincode 600017")
    factors = v1.result["area"]["factors"]
    assert [f["factor"] for f in factors] == ["demand", "anchors", "competition", "cannibalisation", "accessibility"]
    assert all({"raw", "normalized", "effective_weight", "contribution", "provenance"} <= f.keys() for f in factors)
    assert 1 <= len(v1.result["hotspots"]) <= 5 and all(h["reasons"] for h in v1.result["hotspots"])
    with engine.connect() as conn:  # stamped with snapshot + config
        assert conn.execute(text("SELECT count(*) FROM config_versions WHERE version = :v"),
                            dict(v=v1.config_version)).scalar() == 1

    v2 = _run(T_NAGAR)
    assert (v2.area_key, v2.version) == (v1.area_key, v1.version + 1)
    assert v2.score == v1.score  # same data + same config → same answer


def test_reports_are_immutable():
    report = _run(T_NAGAR)
    for sql in ("UPDATE area_reports SET score = 99 WHERE id = :id", "DELETE FROM area_reports WHERE id = :id"):
        with engine.connect() as conn, pytest.raises(DBAPIError, match="immutable"):
            conn.execute(text(sql), dict(id=report.id))


def test_compare_explains_the_difference(client):
    a = _run(T_NAGAR)
    b = _run({"mode": "cells", "cells": a.select_cells[:3]})
    body = client.get(f"/areas/reports/{a.id}/compare/{b.id}", headers=headers(Role.BD_MANAGER)).json()
    assert body["flags"] == ["different_area"]
    assert body["score_delta"] == pytest.approx(b.score - a.score, abs=0.1)
    assert {f["factor"] for f in body["factors"]} == {"demand", "anchors", "competition", "cannibalisation",
                                                      "accessibility"}


def test_airport_is_insufficient_data_not_a_fake_score():
    with engine.connect() as conn:
        cells = conn.execute(text("""
            SELECT array_agg(DISTINCT c.parent_h3) FROM h3_cells c
            JOIN osm_landuse l ON l.snapshot_id = c.snapshot_id AND l.name = 'Chennai International Airport'
             AND ST_Intersects(l.geom, ST_Centroid(c.geom))
            WHERE c.snapshot_id = (SELECT max(id) FROM data_snapshots WHERE status = 'ready') AND c.res = 9""")).scalar()
    report = _run({"mode": "cells", "cells": cells})
    assert report.status == "insufficient_data" and report.score is None and report.result["hotspots"] == []
    assert "no rating" in report.narrative["summary"].lower()


@pytest.mark.parametrize("sel,message", [
    ({"mode": "pincode", "pincode": "600045"}, "No boundary for pincode"),        # Tambaram, outside GCC
    ({"mode": "cells", "cells": ["8861892e39fffff"]}, "not selection cells"),      # far outside
])
def test_bad_selections_are_rejected_with_a_reason(sel, message):
    with pytest.raises(SelectionError, match=message):
        _resolve(**sel)


def test_cell_edits_and_caps():
    base = _resolve(**T_NAGAR)
    edited = _resolve(**T_NAGAR, remove_cells=base["select_cells"][:1])
    assert len(edited["score_cells"]) < len(base["score_cells"]) and edited["area_key"] != base["area_key"]
    with pytest.raises(SelectionError, match="minimum"):
        _resolve(mode="cells", cells=base["select_cells"][:1], remove_cells=base["select_cells"][:1])


def test_non_contiguous_selection_is_allowed_but_flagged():
    base = _resolve(**T_NAGAR)
    far = _resolve(mode="pincode", pincode="600118")["select_cells"][0]  # Kodungaiyur
    r = _resolve(mode="cells", cells=[base["select_cells"][0], far])
    assert r["non_contiguous"] and any("contiguous" in w for w in r["warnings"])


def test_outside_locality_is_refused(client):
    loc = client.get("/localities/search", params={"q": "Tambaram"}, headers=headers(Role.BD_MANAGER)).json()
    resp = client.post("/areas/reports", headers=headers(Role.BD_MANAGER),
                       json={"mode": "locality", "locality_id": loc["candidates"][0]["id"]})
    assert resp.status_code == 422 and "outside the service area" in resp.json()["detail"]


def test_area_endpoints_are_bd_manager_only(client):
    for role in (Role.BD_EXECUTIVE, Role.SURVEY_MANAGER, Role.SURVEY_EXECUTIVE):
        assert client.post("/areas/preview", json=T_NAGAR, headers=headers(role)).status_code == 403
        assert client.get("/areas/reports", headers=headers(role)).status_code == 403
    preview = client.post("/areas/preview", json=T_NAGAR, headers=headers(Role.BD_MANAGER)).json()
    assert preview["score_cell_count"] > 20 and preview["cells_geojson"]["features"]
