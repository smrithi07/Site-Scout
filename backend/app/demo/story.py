"""A full demo story, so a fresh install opens with history for all four personas (`make demo`).

Everything goes through the real API in-process, as the right user with a reason on every change,
so the audit trail, validation, versions and jobs are genuine. Only three things are demo-specific,
and all are labelled:
  - jobs run on a private "demo" queue, drained here (the live worker never sees them), with no LLM
    providers, so every narrative is the deterministic template (no API calls; `--llm` to allow);
  - lane captures are synthetic (plausible counts by road type) and stored with source demo_seed, so
    every summary and evaluation built on them says "mock";
  - capture times are spread over the last few days and time bands, like real field days.

The story:
  Meera (BD Manager) analyses T Nagar (600017) and the top opportunity pocket, and tasks Karthik.
  Karthik (BD Executive) onboards six properties. Meera moves them through the pipeline:
    1 T Nagar corner unit — shortlisted → study (reuses past data, fills the gap) → surveyed by
                            Arjun → Catchment Summary → evaluation v2 with the v1→v2 diff
    2 T Nagar shopfront   — ~450 m away: its study reuses study 1's fresh lanes; Arjun is partway
                            through unit 1
    3 T Nagar ground floor— under review, open follow-up (photos) for Karthik
    4 Pudupet market road — shortlisted, study requested: waiting in Divya's inbox
    5 Pudupet side street — area missing → Needs Info
    6 Near a Savomart store  — ~200 m from an existing store → hard flag → rejected
  Plus a possible duplicate of property 1 for Karthik to resolve.

  python -m app.demo.story            # seed (refuses if the story is already there)
  python -m app.demo.story --purge    # remove the story's properties, tasks, studies and captures
"""
import argparse
import logging
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.auth import token_for
from app.core.config import load_config
from app.core.db import SessionLocal, engine
from app.demo import seed_captures
from app.jobs import queue
from app.jobs.worker import run_once
from app.llm import adapter
from app.services import captures

NS = uuid.UUID("0d3c9a62-51f4-4a8e-9b0e-6d2a7c4e1f58")
MEERA, KARTHIK, DIVYA, ARJUN = 1, 2, 3, 4
H = {uid: {"Authorization": f"Bearer {token_for(uid)}"} for uid in (MEERA, KARTHIK, DIVYA, ARJUN)}
IST = timezone(timedelta(hours=5, minutes=30))
A_STORE = (0.0, 0.0)
PROPERTY_KEYS = [f"p{i}" for i in range(1, 8)]


def cid(key: str) -> str:
    """Deterministic, so a re-run is idempotent; version-4 shaped, as the API requires of phones."""
    return str(uuid.UUID(bytes=uuid.uuid5(NS, key).bytes, version=4))


class Story:
    def __init__(self, llm: bool):
        from app.main import app
        queue.DEFAULT_QUEUE = "demo"                  # our jobs never reach the live worker
        captures.SOURCE = "demo_seed"                 # synthetic lanes are labelled mock
        if not llm:
            adapter.configured_providers = lambda: ()  # template narratives, no API calls
        logging.getLogger("httpx").setLevel(logging.WARNING)   # one line per API call is noise here
        self.c = TestClient(app)
        self.c.__enter__()
        self.rng = random.Random(29)
        self.jobs_cfg = {**load_config()["jobs"], "queues": ["demo"]}

    # --- plumbing ---------------------------------------------------------------------------
    def call(self, method: str, path: str, who: int, body: dict | None = None, ok=(200, 201, 202)) -> dict:
        r = self.c.request(method, path, json=body, headers=H[who])
        if r.status_code not in ok:
            raise SystemExit(f"{method} {path} → {r.status_code}: {r.text[:400]}")
        return r.json()

    def drain(self) -> None:
        while (res := run_once("demo-story", self.jobs_cfg)) is not None:
            if res[1] != "succeeded":
                raise SystemExit(f"job {res[0]} {res[1]} — see the jobs table")

    def say(self, msg: str) -> None:
        print(f"  {msg}", flush=True)

    # --- M1 -------------------------------------------------------------------------------------
    def report(self, selection: dict) -> dict:
        run = self.call("POST", "/areas/reports", MEERA, selection)
        self.drain()
        rid = self.call("GET", f"/areas/reports?area_key={run['area_key']}", MEERA)[0]["id"]
        r = self.call("GET", f"/areas/reports/{rid}", MEERA)
        self.say(f"area report #{r['id']} {r['label']}: {r['score']} {r['rating']}")
        return r

    def task(self, report: dict, title: str, note: str, hotspots: int) -> dict:
        t = self.call("POST", "/tasks", MEERA, {
            "title": title, "assignee_id": KARTHIK, "source_report_id": report["id"], "note": note,
            "due_date": (datetime.now(IST).date() + timedelta(days=5)).isoformat(),
            "hotspot_cells": [h["h3"] for h in report["result"]["hotspots"][:hotspots]]})
        self.say(f"scout task #{t['id']} → Karthik: {title}")
        return t

    # --- M2 -------------------------------------------------------------------------------------
    def onboard(self, key: str, spot: tuple[float, float], task: dict | None, **fields) -> dict:
        body = {"client_id": cid(key), "lat": round(spot[0], 6), "lon": round(spot[1], 6), "gps_accuracy_m": 6,
                "device_lat": round(spot[0] + 0.00005, 6), "device_lon": round(spot[1], 6),
                "rent_unit": "per_month", "floor": "ground", "owner_name": "Owner (demo)",
                "owner_phone": "+91 90000 00000", "task_id": task["id"] if task else None, **fields}
        p = self.call("POST", "/properties", KARTHIK, body)
        self.drain()                                              # evaluation v1
        p = self.call("GET", f"/properties/{p['id']}", MEERA)
        ev = p.get("evaluation") or {}
        self.say(f"property #{p['id']} {p['label']}: {ev.get('outcome')} {ev.get('score')}")
        return p

    def move(self, p: dict, to: str, reason: str) -> dict:
        return self.call("POST", f"/properties/{p['id']}/stage", MEERA, {"to": to, "reason": reason, "version": p["version"]})

    def note(self, p: dict, who: int, text_: str) -> None:
        self.call("POST", f"/properties/{p['id']}/notes", who, {"text": text_})

    # --- M3 -------------------------------------------------------------------------------------
    def request_study(self, p: dict, reason: str) -> dict:
        s = self.call("POST", "/studies", MEERA, {"property_id": p["id"], "version": p["version"],
                                                  "mode": "reuse_and_fill", "reason": reason})
        self.say(f"study #{s['id']} requested for {p['label']}")
        return s

    def plan(self, s: dict) -> dict:
        self.call("POST", f"/studies/{s['id']}/plan", DIVYA, {"version": s["version"], "mode": "reuse_and_fill"})
        self.drain()
        plan = self.call("GET", f"/studies/{s['id']}/units", DIVYA)
        self.say(f"study #{s['id']} planned: {len(plan['units'])} units")
        return plan

    def assign(self, plan: dict, unit: dict) -> dict:
        return self.call("POST", f"/studies/{plan['study']['id']}/units/{unit['id']}/assign", DIVYA,
                         {"version": plan["study"]["version"], "assignee_id": ARJUN})

    def lanes(self, unit: dict) -> list[dict]:
        fc = self.call("GET", f"/units/{unit['id']}/segments", ARJUN)
        lanes = sorted((f["properties"] for f in fc["features"]), key=lambda x: x["order"])
        with engine.connect() as conn:
            for lane in lanes:
                lane["lat"], lane["lon"] = conn.execute(text("""
                    SELECT ST_Y(ST_LineInterpolatePoint(r.geom, 0.5)), ST_X(ST_LineInterpolatePoint(r.geom, 0.5))
                    FROM road_segments r JOIN survey_units u ON true JOIN studies s ON s.id = u.study_id
                    WHERE u.id = :u AND r.snapshot_id = s.snapshot_id AND r.segment_id = :g"""),
                    dict(u=unit["id"], g=lane["segment_id"])).one()
        return lanes

    def walk(self, unit: dict, day: int, band_hour: int, share: float = 1.0, gated: int = 0) -> int:
        """Arjun captures a unit on one field day, starting at `band_hour` IST, one lane after another."""
        lanes = self.lanes(unit)
        todo = lanes[: max(1, round(len(lanes) * share))]
        start = (datetime.now(IST) - timedelta(days=day)).replace(hour=band_hour, minute=5, second=0, microsecond=0)
        for i, lane in enumerate(todo):
            at = start + timedelta(minutes=6 * i)
            blocked = i in {len(todo) // 2 + k for k in range(gated)}
            body = {"client_id": cid(f"cap-{unit['id']}-{lane['segment_id']}"), "unit_id": unit["id"],
                    "segment_id": lane["segment_id"], "lat": lane["lat"], "lon": lane["lon"], "gps_accuracy_m": 7,
                    "captured_at": at.isoformat(), "notes": "demo story (synthetic)"}
            if blocked:
                body |= {"status": "could_not_survey", "reason": "Gated lane — security would not allow entry"}
            else:
                body |= {"status": "surveyed",
                         "observations": seed_captures.observations(self.rng, lane.get("highway") or "residential",
                                                                    lane.get("length_m") or 50)}
            self.call("POST", "/captures", ARJUN, body)
        return len(todo)

    # --- the story ------------------------------------------------------------------------------
    def run(self) -> None:
        print("M1 — Meera analyses areas")
        tnagar = self.report({"mode": "pincode", "pincode": "600017"})
        pocket = self.call("GET", "/opportunities", MEERA)["pockets"][0]
        self.say(f"top opportunity pocket: {pocket['label']} ({pocket['score']})")
        pudupet = self.report(pocket["selection"])
        t1 = self.task(tnagar, "Scout T Nagar hotspots 1–2", "Ground-floor units on busy streets, 800–1,200 sq ft.", 2)
        t2 = self.task(pudupet, f"Scout {pocket['label'].split(' (')[0]} pocket",
                       "Surfaced by the opportunity map — nobody has visited yet.", 2)
        hs, hp = tnagar["result"]["hotspots"], pudupet["result"]["hotspots"]

        print("M2 — Karthik onboards, Meera reviews")
        p1 = self.onboard("p1", (hs[0]["lat"], hs[0]["lon"]), t1, label="T Nagar corner unit", monthly_rent=145000,
                          area_sqft=1100, frontage_ft=24, road_width_ft=40, visibility="good", accessibility="good",
                          parking="limited", condition="good", security_deposit=900000, availability="Immediate",
                          locality="T Nagar")
        # ~450 m from p1: the catchments overlap, so study 2 can reuse Arjun's fresh study-1 lanes.
        p2 = self.onboard("p2", (hs[0]["lat"] + 0.0040, hs[0]["lon"] + 0.0008), t1, label="T Nagar main-road shopfront", monthly_rent=118000,
                          area_sqft=950, frontage_ft=18, road_width_ft=30, visibility="good", accessibility="fair",
                          parking="none", condition="fair", locality="T Nagar")
        p3 = self.onboard("p3", (hs[1]["lat"], hs[1]["lon"]), t1, label="T Nagar ground-floor unit", monthly_rent=98000,
                          area_sqft=900, frontage_ft=14, road_width_ft=20, visibility="fair", accessibility="fair",
                          parking="none", condition="fair", locality="T Nagar")
        p4 = self.onboard("p4", (hp[0]["lat"], hp[0]["lon"]), t2, label="Market road unit (Pudupet pocket)", monthly_rent=72000,
                          area_sqft=1000, frontage_ft=20, road_width_ft=26, visibility="good", accessibility="good",
                          parking="limited", condition="fair")
        p5 = self.onboard("p5", (hp[1]["lat"], hp[1]["lon"]), t2, label="Side-street shop (Pudupet pocket)", monthly_rent=55000,
                          frontage_ft=12, visibility="fair", accessibility="fair")            # no area → Needs Info
        p6 = self.onboard("p6", (A_STORE[0] + 0.0016, A_STORE[1] + 0.0007), None,
                          label="Main road unit near a Savomart store", monthly_rent=48000, area_sqft=1200, frontage_ft=22,
                          road_width_ft=40, visibility="good", accessibility="good", parking="limited")
        dup = self.onboard("p7", (hs[0]["lat"] + 0.00008, hs[0]["lon"]), t1, label="T Nagar corner shop",
                           monthly_rent=150000, area_sqft=1100)
        self.say(f"#{dup['id']} flagged as a possible duplicate of #{p1['id']} — for Karthik to resolve")
        self.note(p1, KARTHIK, "Owner is open to a 9-year lease with a 5% escalation every 3 years.")

        p1 = self.move(p1, "under_review", "Strong first evaluation; corner visibility on a main road")
        p2 = self.move(p2, "under_review", "Good frontage, close to the corner unit")
        p3 = self.move(p3, "under_review", "Worth a look — narrower frontage")
        p4 = self.move(p4, "under_review", "First site from the opportunity map")
        p6 = self.move(p6, "rejected", "a Savomart store is ~200 m away — cannibalisation (hard flag)")
        self.call("POST", f"/properties/{p3['id']}/follow-ups", MEERA, {
            "kind": "photos", "message": "Please add photos of the frontage and the street from both directions.",
            "version": p3["version"]})
        p1 = self.move(p1, "shortlisted", "Top candidate in T Nagar; commission a catchment study")
        p2 = self.move(p2, "shortlisted", "Backup to the corner unit")
        p4 = self.move(p4, "shortlisted", "Promising pocket; validate footfall on the ground")

        print("M3 — study 1: reuse past data, survey the gap, roll up, re-evaluate")
        seed_captures.seed(p1["id"], coverage=0.55, stale=0.12, gap=0.02, rng_seed=17)
        s1 = self.request_study(p1, "Validate footfall and competition before approving")
        plan = self.plan(s1)
        for u in plan["units"]:
            plan = self.assign(plan, u)
        for i, u in enumerate(plan["units"]):
            n = self.walk(u, day=4 - i % 4, band_hour=[8, 17, 12, 18][i % 4], gated=1 if i == 0 else 0)
            self.call("POST", f"/units/{u['id']}/submit", ARJUN)
            self.say(f"{u['label']}: {n} lanes captured and submitted")
        self.drain()                                              # roll-up → evaluation v2
        v2 = self.call("GET", f"/properties/{p1['id']}", MEERA)["evaluation"]
        self.say(f"#{p1['id']} evaluation v{v2['version']}: {v2['outcome']} {v2['score']}")

        print("M3 — study 2: in progress")
        s2 = self.request_study(p2, "Second site in T Nagar; check it against the corner-unit study")
        plan2 = self.plan(s2)
        plan2 = self.assign(plan2, plan2["units"][0])
        n = self.walk(plan2["units"][0], day=1, band_hour=9, share=0.6, gated=1)
        self.say(f"{plan2['units'][0]['label']}: {n} lanes captured so far (unit still open)")

        print("M3 — study 3: requested, waiting for Divya")
        self.request_study(p4, "Opportunity-map site: confirm demand before committing")
        print("done")


def exists() -> bool:
    with engine.connect() as conn:
        return bool(conn.execute(text("SELECT count(*) FROM properties WHERE client_id = ANY(:c)"),
                                 dict(c=[cid(k) for k in PROPERTY_KEYS])).scalar())


def purge() -> None:
    """Remove the story's properties and everything hanging off them (immutable rows via the purge
    switch). Area reports stay: they're immutable history, and a re-run just adds a version."""
    with SessionLocal() as db:
        db.execute(text("SET LOCAL sitescout.purge = 'on'"))
        ids = db.execute(text("SELECT id FROM properties WHERE client_id = ANY(:c)"),
                         dict(c=[cid(k) for k in PROPERTY_KEYS])).scalars().all()
        sids = db.execute(text("SELECT id FROM studies WHERE property_id = ANY(:i)"), dict(i=ids)).scalars().all()
        db.execute(text("DELETE FROM property_evaluations WHERE property_id = ANY(:i)"), dict(i=ids))
        for sql in ("UPDATE studies SET rollup_job_id = NULL WHERE id = ANY(:s)",
                    "DELETE FROM study_segments WHERE study_id = ANY(:s)",
                    "DELETE FROM segment_captures WHERE study_id = ANY(:s)",
                    "DELETE FROM survey_units WHERE study_id = ANY(:s)",
                    "DELETE FROM catchment_summaries WHERE study_id = ANY(:s)"):
            db.execute(text(sql), dict(s=sids))
        db.execute(text("DELETE FROM studies WHERE id = ANY(:s)"), dict(s=sids))
        for table in ("property_notes", "property_photos", "follow_ups"):
            db.execute(text(f"DELETE FROM {table} WHERE property_id = ANY(:i)"), dict(i=ids))
        db.execute(text("UPDATE properties SET duplicate_of = NULL WHERE id = ANY(:i)"), dict(i=ids))
        tasks = db.execute(text("SELECT DISTINCT task_id FROM properties WHERE id = ANY(:i) AND task_id IS NOT NULL"),
                           dict(i=ids)).scalars().all()
        db.execute(text("DELETE FROM properties WHERE id = ANY(:i)"), dict(i=ids))
        db.execute(text("DELETE FROM scout_tasks WHERE id = ANY(:t)"), dict(t=tasks))
        db.commit()
    print(f"purged {len(ids)} properties, {len(sids)} studies, {len(tasks)} tasks")


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m app.demo.story")
    ap.add_argument("--purge", action="store_true", help="remove the story (then run again to reseed)")
    ap.add_argument("--llm", action="store_true", help="let the configured LLM providers write narratives")
    args = ap.parse_args()
    if args.purge:
        purge()
        return 0
    if exists():
        print("The demo story is already seeded (make demo ARGS=--purge to remove it first).")
        return 0
    Story(llm=args.llm).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
