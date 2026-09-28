"""Phase 6a checkpoint: bad pins and duplicates are handled correctly, executives see only their own
properties, wrong roles get 403, stale edits get 409, photos are optional and flagged when missing."""
import shutil
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.auth import Role
from app.core.db import SessionLocal, engine
from app.core.settings import get_settings
from app.jobs import queue
from app.jobs.worker import run_once
from app.models import AreaReport, User
from tests.conftest import USER_IDS, headers

BDM, BDE = headers(Role.BD_MANAGER), headers(Role.BD_EXECUTIVE)
PONDY_BAZAAR = (13.0418, 80.2341)   # T Nagar, inside GCC


@pytest.fixture(autouse=True)
def cleanup():
    yield
    with engine.begin() as conn:
        ids = conn.execute(text("SELECT id FROM properties WHERE label LIKE 'TEST %'")).scalars().all()
        conn.execute(text("DELETE FROM property_notes WHERE property_id = ANY(:i)"), dict(i=ids))
        conn.execute(text("DELETE FROM property_photos WHERE property_id = ANY(:i)"), dict(i=ids))
        conn.execute(text("UPDATE properties SET duplicate_of = NULL WHERE id = ANY(:i)"), dict(i=ids))
        conn.execute(text("DELETE FROM properties WHERE id = ANY(:i)"), dict(i=ids))
        conn.execute(text("DELETE FROM scout_tasks WHERE title LIKE 'TEST %'"))
        conn.execute(text("SET LOCAL sitescout.purge = 'on'"))
        conn.execute(text("DELETE FROM area_reports WHERE job_id IN (SELECT id FROM jobs WHERE queue = 'test')"))
        conn.execute(text("DELETE FROM jobs WHERE queue = 'test'"))
    for i in ids:
        shutil.rmtree(Path(get_settings().upload_dir) / "properties" / str(i), ignore_errors=True)


def prop(label: str | None = None, lat: float = PONDY_BAZAAR[0], lon: float = PONDY_BAZAAR[1], **extra) -> dict:
    body = {"client_id": str(uuid.uuid4()), "label": label or f"TEST shop {uuid.uuid4().hex[:6]}", "lat": lat, "lon": lon,
            "gps_accuracy_m": 8, "monthly_rent": 120000, "rent_unit": "per_month", "area_sqft": 1000,
            "owner_name": "Owner", "owner_phone": "+91 90000 00000", **extra}
    if not body["label"].startswith("TEST "):
        body["label"] = "TEST " + body["label"]
    return body


def post(client, body, h=BDE):
    return client.post("/properties", json=body, headers=h)


# --- tasks -------------------------------------------------------------------------------

def _report() -> AreaReport:
    with SessionLocal() as db:
        job = queue.enqueue(db, "area_report", {"selection": {"mode": "pincode", "pincode": "600017"},
                                                "actor_id": USER_IDS[Role.BD_MANAGER]},
                            db.get(User, USER_IDS[Role.BD_MANAGER]), queue="test")
        db.commit()
        job_id = job.id
    run_once("w-test", {"queues": ["test"], "heartbeat_seconds": 1, "stale_after_seconds": 30, "max_attempts": 3})
    with SessionLocal() as db:
        return db.query(AreaReport).filter(AreaReport.job_id == job_id).one()


def test_task_from_hotspots_and_who_can_do_what(client):
    report = _report()
    hotspots = [h["h3"] for h in report.result["hotspots"][:2]]
    body = {"title": "TEST scout T Nagar", "assignee_id": USER_IDS[Role.BD_EXECUTIVE], "source_report_id": report.id,
            "hotspot_cells": hotspots}
    assert client.post("/tasks", json=body, headers=BDE).status_code == 403          # executives can't create
    bad = client.post("/tasks", json={**body, "assignee_id": USER_IDS[Role.BD_MANAGER]}, headers=BDM)
    assert bad.status_code == 422                                                    # only executives are assignees
    task = client.post("/tasks", json=body, headers=BDM).json()
    assert len(task["target_cells"]) >= 1

    mine = client.get(f"/tasks/{task['id']}", headers=BDE).json()
    assert [h["h3"] for h in mine["hotspots"]] == hotspots                          # exec sees only the task's hotspots
    assert client.get("/tasks", headers=headers(Role.SURVEY_MANAGER)).status_code == 403

    # Onboarding a property under the task moves it to in_progress; exec can finish, not cancel.
    assert post(client, prop(task_id=task["id"])).status_code == 201
    t = client.get(f"/tasks/{task['id']}", headers=BDE).json()
    assert t["status"] == "in_progress" and len(t["properties"]) == 1
    cancel = client.patch(f"/tasks/{task['id']}", json={"version": t["version"], "status": "cancelled", "reason": "nah"},
                          headers=BDE)
    assert cancel.status_code == 403
    done = client.patch(f"/tasks/{task['id']}", json={"version": t["version"], "status": "done", "reason": "scouted"},
                        headers=BDE)
    assert done.json()["status"] == "done"


# --- save-first + validation ------------------------------------------------------------

def test_save_first_and_retry_is_idempotent(client):
    body = prop()
    first = post(client, body)
    again = post(client, body)
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json()["id"] == again.json()["id"]
    assert first.json()["pincode"] == "600017" and first.json()["ward_no"]           # prefilled from the pin


def _water_point() -> tuple[float, float]:
    with engine.connect() as conn:
        return tuple(conn.execute(text("""
            SELECT ST_Y(p), ST_X(p) FROM (
              SELECT ST_PointOnSurface(l.geom) AS p FROM osm_landuse l, service_areas sa
              WHERE l.snapshot_id = sa.snapshot_id AND sa.snapshot_id = (SELECT max(id) FROM data_snapshots WHERE status='ready')
                AND l.lclass = 'water' AND ST_Within(l.geom, sa.geom)
              ORDER BY ST_Area(l.geom) DESC LIMIT 1) x""")).one())


@pytest.mark.parametrize("override,message", [
    ({"lat": 0.0, "lon": 0.0}, "(0, 0)"),
    ({"lat": 12.9249, "lon": 80.1000}, "outside the service area"),                  # Tambaram
    ({"monthly_rent": -5}, "greater than or equal to 0"),
    ({"monthly_rent": 5000, "rent_unit": None}, "rent_unit is required"),
])
def test_bad_input_is_rejected_with_a_reason(client, override, message):
    r = post(client, prop(**override))
    assert r.status_code == 422 and message in str(r.json()["detail"])


def test_pin_in_water_is_rejected(client):
    lat, lon = _water_point()
    r = post(client, prop(lat=lat, lon=lon))
    assert r.status_code == 422 and "water" in r.json()["detail"]


def test_warnings_never_block_the_save(client):
    r = post(client, prop(gps_accuracy_m=180, device_lat=13.0827, device_lon=80.2707,   # executive ~5 km away
                          monthly_rent=5000, area_sqft=1000))                              # ₹5/sq ft: far below band
    assert r.status_code == 201
    codes = {w["code"] for w in r.json()["warnings"]}
    assert codes == {"gps_poor", "far_from_executive", "rent_outlier"}
    zero = post(client, prop(monthly_rent=0, area_sqft=None)).json()
    assert "rent_zero" in {w["code"] for w in zero["warnings"]}
    assert set(zero["missing_fields"]) == {"monthly_rent", "area_sqft", "photos"}      # never guessed


# --- duplicates -------------------------------------------------------------------------

def test_duplicate_is_flagged_and_resolved_explicitly(client):
    a = post(client, prop(label="TEST Sri Murugan Stores")).json()
    b = post(client, prop(label="TEST Sri Murugan Store", lat=PONDY_BAZAAR[0] + 0.00008)).json()   # ~9 m away
    assert b["status"] == "possible_duplicate" and b["duplicate_candidates"][0]["id"] == a["id"]
    wrong = client.post(f"/properties/{b['id']}/duplicate-resolution", json={"choice": "same", "target_id": 999999},
                        headers=BDE)
    assert wrong.status_code == 422
    merged = client.post(f"/properties/{b['id']}/duplicate-resolution", json={"choice": "same", "target_id": a["id"]},
                         headers=BDE).json()
    assert merged["status"] == "merged" and merged["duplicate_of"] == a["id"]
    notes = client.get(f"/properties/{a['id']}", headers=BDE).json()["notes"]
    assert notes[-1]["kind"] == "duplicate_merge" and f"#{b['id']}" in notes[-1]["text"]

    c = post(client, prop(label="TEST Sri Murugan Stores", lat=PONDY_BAZAAR[0] - 0.00008)).json()
    kept = client.post(f"/properties/{c['id']}/duplicate-resolution", json={"choice": "different"}, headers=BDE).json()
    assert kept["status"] == "active" and "possible_duplicate" not in {w["code"] for w in kept["warnings"]}


def test_far_or_dissimilar_is_not_a_duplicate(client):
    post(client, prop(label="TEST Lakshmi Provisions"))
    far = post(client, prop(label="TEST Lakshmi Provisions", lat=PONDY_BAZAAR[0] + 0.001)).json()      # ~110 m
    other = post(client, prop(label="TEST Chennai Mobiles", lat=PONDY_BAZAAR[0] + 0.00005)).json()     # different name
    assert far["status"] == other["status"] == "active"


# --- access, masking, locking, photos ---------------------------------------------------

def test_executives_see_only_their_own(client):
    managers = post(client, prop(), h=BDM).json()
    assert client.get(f"/properties/{managers['id']}", headers=BDE).status_code == 403
    assert managers["id"] not in {p["id"] for p in client.get("/properties", headers=BDE).json()}
    assert managers["id"] in {p["id"] for p in client.get("/properties", headers=BDM).json()}
    for role in (Role.SURVEY_MANAGER, Role.SURVEY_EXECUTIVE):
        assert client.get("/properties", headers=headers(role)).status_code == 403
        assert client.post("/properties", json=prop(), headers=headers(role)).status_code == 403


def test_stale_edit_conflicts_and_edits_are_revalidated(client):
    p = post(client, prop()).json()
    ok = client.patch(f"/properties/{p['id']}", json={"version": p["version"], "changes": {"frontage_ft": 22}}, headers=BDE)
    assert ok.status_code == 200 and ok.json()["version"] == p["version"] + 1
    stale = client.patch(f"/properties/{p['id']}", json={"version": p["version"], "changes": {"frontage_ft": 30}}, headers=BDE)
    assert stale.status_code == 409
    lat, lon = _water_point()
    moved = client.patch(f"/properties/{p['id']}", json={"version": ok.json()["version"], "changes": {"lat": lat, "lon": lon}},
                         headers=BDE)
    assert moved.status_code == 422


PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082")


def test_photos_are_optional_and_uploaded_separately(client):
    p = post(client, prop()).json()
    assert "photos" in p["missing_fields"]
    bad = client.post(f"/properties/{p['id']}/photos", files={"file": ("x.gif", b"GIF89a", "image/gif")}, headers=BDE)
    assert bad.status_code == 422
    up = client.post(f"/properties/{p['id']}/photos", files={"file": ("front.png", PNG, "image/png")}, headers=BDE)
    assert up.status_code == 201
    after = client.get(f"/properties/{p['id']}", headers=BDE).json()
    assert "photos" not in after["missing_fields"] and after["photos"][0]["filename"] == "front.png"
    img = client.get(f"/properties/{p['id']}/photos/{up.json()['id']}", headers=BDE)
    assert img.status_code == 200 and img.content == PNG


def test_every_change_is_audited(client):
    p = post(client, prop()).json()
    client.patch(f"/properties/{p['id']}", json={"version": p["version"], "changes": {"floor": "ground"}}, headers=BDE)
    trail = client.get("/audit", params={"entity_type": "property", "entity_id": p["id"]}, headers=BDM).json()
    assert [e["action"] for e in trail] == ["created", "edited"]
    assert trail[1]["details"]["fields"] == ["floor"] and trail[1]["actor_role"] == "bd_executive"
