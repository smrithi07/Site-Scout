"""M3 roll-up: lane captures → Catchment Summary (docs/DESIGN.md §7 Roll-up).

Which capture counts for a lane: its latest capture in THIS study; otherwise, for a lane the plan
reused, the fresh capture it reused (never under full_survey). Every aggregate is computed over
SURVEYED lanes only — could-not-survey lanes are handled but carry no data, and unsurveyed lanes
are never filled in, except the one clearly-labelled estimate (competition across the catchment).

Per lane provenance: observed (this study, field) · observed_reused (an earlier field survey) ·
mock (demo seed). The summary states the shares; mock data lowers confidence and is always named.

Scores are normalised with config thresholds that are UNCALIBRATED assumptions (no citywide
baseline yet); below `min_coverage` the summary is facts only — no scores at all.
"""
import math

from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import Role
from app.core.config import load_config
from app.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from app.core.locking import update_versioned
from app.models import CatchmentSummary, Job, Property, Study, SurveyUnit, User
from app.schemas.studies import LaneObservations
from app.services import pipeline

LEVELS = ["low", "medium", "high"]


def _cfg() -> dict:
    return load_config()["studies"]["rollup"]


# --- collection (DB) ---------------------------------------------------------------------

def collect(db: Session, study: Study) -> dict:
    """Everything the aggregation needs, as plain JSON (the job persists it between steps)."""
    mode = study.planned_mode or study.requested_mode
    lanes = [dict(r) for r in db.execute(text("""
        SELECT ss.segment_id, ss.length_m, ss.to_survey,
               ST_X(ST_Transform(ST_LineInterpolatePoint(r.geom, 0.5), 32644)) AS x,
               ST_Y(ST_Transform(ST_LineInterpolatePoint(r.geom, 0.5), 32644)) AS y,
               own.status AS own_status, own.observations AS own_obs, own.time_band AS own_band, own.source AS own_source,
               own.captured_at AS own_at,
               re.status AS re_status, re.observations AS re_obs, re.time_band AS re_band, re.source AS re_source,
               re.captured_at AS re_at
        FROM study_segments ss
        JOIN road_segments r ON r.snapshot_id = :snap AND r.segment_id = ss.segment_id
        LEFT JOIN LATERAL (SELECT * FROM segment_captures c WHERE c.study_id = ss.study_id AND c.segment_id = ss.segment_id
                           ORDER BY c.captured_at DESC LIMIT 1) own ON true
        LEFT JOIN segment_captures re ON re.id = ss.reused_capture_id AND :reuse
        WHERE ss.study_id = :s"""), dict(s=study.id, snap=study.snapshot_id, reuse=mode != "full_survey")).mappings()]
    out = []
    for l in lanes:
        if l["own_status"]:
            cap = {"status": l["own_status"], "obs": l["own_obs"], "band": l["own_band"], "at": l["own_at"].isoformat(),
                   "provenance": "mock" if l["own_source"] == "demo_seed" else "observed"}
        elif l["re_status"]:
            cap = {"status": l["re_status"], "obs": l["re_obs"], "band": l["re_band"], "at": l["re_at"].isoformat(),
                   "provenance": "mock" if l["re_source"] == "demo_seed" else "observed_reused"}
        else:
            cap = None
        out.append({"segment_id": l["segment_id"], "length_m": l["length_m"], "x": l["x"], "y": l["y"], "capture": cap})
    osm = db.scalar(text("""
        SELECT count(*) FROM osm_pois
        WHERE snapshot_id = :snap AND category = 'competitor'
          AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :r)"""),
        dict(snap=study.snapshot_id, lat=study.lat, lon=study.lon, r=study.radius_m))
    return {"lanes": out, "osm_competitors": osm, "mode": mode, "radius_m": study.radius_m}


# --- aggregation (pure) --------------------------------------------------------------------

def _norm(v: float | None, lo_hi: list, invert: bool = False) -> float | None:
    if v is None:
        return None
    lo, hi = lo_hi
    x = max(0.0, min(100.0, (v - lo) / (hi - lo) * 100))
    return round(100 - x if invert else x, 1)


def _lw(lanes: list[dict], fn) -> float | None:
    """Length-weighted mean of fn(lane) over lanes."""
    total = sum(l["length_m"] for l in lanes)
    return sum(fn(l) * l["length_m"] for l in lanes) / total if total else None


def _dedupe_anchors(items: list[dict], within_m: float) -> list[dict]:
    """Same type, same (or unknown) name, and close together = one anchor seen from two lanes."""
    kept: list[dict] = []
    for a in sorted(items, key=lambda a: (a["type"], a["name"] is None)):   # named first
        dup = next((k for k in kept if k["type"] == a["type"] and math.hypot(k["x"] - a["x"], k["y"] - a["y"]) <= within_m
                    and (a["name"] is None or k["name"] is None or k["name"].casefold() == a["name"].casefold())), None)
        if dup:
            dup["lanes"] += 1
            dup["name"] = dup["name"] or a["name"]
        else:
            kept.append({**a, "lanes": 1})
    return kept


def _usable(capture: dict) -> bool:
    try:
        LaneObservations.model_validate(capture["obs"])
        return True
    except ValidationError:
        return False


def aggregate(data: dict, cfg: dict) -> dict:
    lanes, mode = data["lanes"], data["mode"]
    total = sum(l["length_m"] for l in lanes)
    claimed = [l for l in lanes if l["capture"] and l["capture"]["status"] == "surveyed"]
    surveyed = [l for l in claimed if _usable(l["capture"])]   # malformed/old-schema data never skews a value
    unusable = len(claimed) - len(surveyed)
    gaps = [l for l in lanes if l["capture"] and l["capture"]["status"] == "could_not_survey"]
    S = sum(l["length_m"] for l in surveyed)
    G = sum(l["length_m"] for l in gaps)
    coverage = S / total if total else 0.0
    facts_only = coverage < cfg["min_coverage"]
    by_src = {p: sum(l["length_m"] for l in surveyed if l["capture"]["provenance"] == p)
              for p in ("observed", "observed_reused", "mock")}
    shares = {p: round(v / S, 3) if S else 0.0 for p, v in by_src.items()}
    # A signal is labelled by its source when one source is ≥ 90% of the surveyed length (so 99% demo
    # data reads "mock", not "mixed"); the exact shares are always reported alongside.
    prov = next((p for p, sh in shares.items() if sh >= 0.9), "mixed") if S else "missing"
    ordv = cfg["ordinal"]
    norm = cfg["normalize"]
    obs = lambda l: l["capture"]["obs"]  # noqa: E731
    per100 = lambda key: (sum(obs(l)[key] for l in surveyed) / S * 100) if S else None  # noqa: E731

    def signal(value, unit, lanes_n, normalized=None, notes=(), **extra):
        return {"value": None if value is None else round(value, 2), "unit": unit, "lanes": lanes_n,
                "normalized": None if facts_only else normalized, "provenance": prov, "notes": list(notes), **extra}

    # footfall: timed count → hourly rate per lane; length-weighted; time-band mix
    rate = lambda l: obs(l)["pedestrians_counted"] / obs(l)["count_minutes"] * 60  # noqa: E731
    bands: dict[str, float] = {}
    for l in surveyed:
        bands[l["capture"]["band"] or "unknown"] = bands.get(l["capture"]["band"] or "unknown", 0) + l["length_m"]
    band_share = {b: round(v / S, 3) for b, v in sorted(bands.items())} if S else {}
    top_band = max(band_share.items(), key=lambda kv: kv[1]) if band_share else (None, 0)
    single_band = top_band[1] >= cfg["single_band_share"]
    footfall = _lw(surveyed, rate)
    foot_notes = [f"{round(top_band[1] * 100)}% of surveyed length was counted in the {top_band[0]} band — "
                  "footfall at other times of day is not observed"] if single_band else []

    # competition: observed on surveyed lanes; a labelled estimate across the catchment; vs OSM
    found = sum(obs(l)["grocery_food_stores"] for l in surveyed)
    per_km = found / (S / 1000) if S else None
    est_total = per_km * total / 1000 if per_km is not None else None
    osm = data["osm_competitors"]
    comp_notes = []
    if est_total is not None:
        comp_notes.append(f"{found} found on {round(coverage * 100)}% of the catchment's lanes; ≈{round(est_total)} "
                          "across the whole catchment (estimate, assumes unsurveyed lanes are similar)")
        comp_notes.append(f"OpenStreetMap lists {osm}" + (f" — the survey suggests OSM undercounts about "
                                                           f"{est_total / osm:.1f}×" if osm and est_total > osm else ""))

    access = lambda l: (ordv[obs(l)["road_width_band"]] + ordv[obs(l)["pedestrian_access"]] + ordv[obs(l)["vehicle_access"]]) / 3  # noqa: E731
    acc = _lw(surveyed, access)
    poor_share = (sum(l["length_m"] for l in surveyed if "poor" in (obs(l)["pedestrian_access"], obs(l)["vehicle_access"])) / S
                  if S else None)
    park = _lw(surveyed, lambda l: ordv[obs(l)["parking"]])
    park_share = sum(l["length_m"] for l in surveyed if obs(l)["parking"] != "none") / S if S else None

    anchors = _dedupe_anchors([{"type": a["type"], "name": a.get("name"), "x": l["x"], "y": l["y"]}
                               for l in surveyed for a in obs(l).get("anchors", [])], cfg["anchor_dedupe_m"])
    residential, commercial = per100("residential_units"), per100("businesses")
    signals = {
        "residential": signal(residential, "residential units per 100 m", len(surveyed),
                              _norm(residential, norm["residential_per_100m"])),
        "commercial": signal(commercial, "businesses per 100 m", len(surveyed), _norm(commercial, norm["commercial_per_100m"])),
        "footfall": signal(footfall, "pedestrians per hour (length-weighted)", len(surveyed),
                           _norm(footfall, norm["footfall_per_hour"]), foot_notes, time_bands=band_share, single_band=single_band),
        "accessibility": signal(None if acc is None else acc * 100, "0–100 (road width, pedestrian and vehicle access)",
                                len(surveyed), None if acc is None else round(acc * 100, 1),
                                share_poor=None if poor_share is None else round(poor_share, 3)),
        "parking": signal(None if park is None else park * 100, "0–100 (none / limited / good)", len(surveyed),
                          None if park is None else round(park * 100, 1),
                          share_with_parking=None if park_share is None else round(park_share, 3)),
        "competition": signal(per_km, "grocery / food stores per km of surveyed lane", len(surveyed),
                              _norm(per_km, norm["competition_per_km"], invert=True), comp_notes,
                              observed_count=found, estimated_catchment_count=None if est_total is None else round(est_total, 1),
                              osm_count=osm),
    }

    # confidence: coverage first, then one step down per weakness (never below low)
    level = 2 if coverage >= cfg["confidence_coverage"]["high"] else 1 if coverage >= cfg["confidence_coverage"]["medium"] else 0
    reasons = [f"{round(coverage * 100)}% of the catchment's road length surveyed"]
    for weak, why in ((single_band, "footfall comes from a single time band"),
                      (mode == "reuse_only", "reuse only — no new survey"),
                      (shares["observed_reused"] > 0.5, f"{round(shares['observed_reused'] * 100)}% of the data is reused from earlier surveys"),
                      (shares["mock"] > 0.5, f"{round(shares['mock'] * 100)}% of the surveyed length is demo (mock) data")):
        if weak:
            level = max(0, level - 1)
            reasons.append(why)
    if 0 < shares["mock"] <= 0.5:
        reasons.append(f"{round(shares['mock'] * 100)}% of the surveyed length is demo (mock) data")
    if unusable:
        reasons.append(f"{unusable} lane capture(s) had unusable data and were left out")
    if facts_only:
        reasons.append(f"below {round(cfg['min_coverage'] * 100)}% coverage: facts only, no scores")
    return {
        "coverage": {"total_length_m": round(total), "surveyed_length_m": round(S), "gap_length_m": round(G),
                     "not_surveyed_length_m": round(total - S - G), "surveyed_share": round(coverage, 3),
                     "lanes": len(lanes), "surveyed_lanes": len(surveyed), "gap_lanes": len(gaps),
                     "unusable_lanes": unusable, "sources": shares,
                     "mode": mode},
        "signals": signals, "anchors": [{k: a[k] for k in ("type", "name", "lanes")} for a in anchors],
        "confidence": LEVELS[level], "confidence_reasons": reasons, "facts_only": facts_only,
    }


# --- orchestration --------------------------------------------------------------------------

def enqueue(db: Session, study: Study, actor: User | None, trigger: str) -> int:
    from app.jobs import queue  # local: jobs import services
    job = queue.enqueue(db, "study_rollup", {"study_id": study.id, "trigger": trigger}, actor)
    db.flush()
    study.rollup_job_id = job.id
    db.flush()
    return job.id


def _job_running(db: Session, study: Study) -> bool:
    return bool(study.rollup_job_id and db.scalar(select(Job.status).where(Job.id == study.rollup_job_id))
                in ("queued", "running"))


def maybe_start(db: Session, study: Study, actor: User | None) -> int | None:
    """Called after a unit is submitted and after planning: roll up once nothing is left to survey."""
    units = list(db.scalars(select(SurveyUnit).where(SurveyUnit.study_id == study.id)))
    if study.status not in ("planned", "in_progress") or _job_running(db, study):
        return None
    if units and any(u.status != "submitted" for u in units):
        return None
    trigger = "all_units_submitted" if units else "reuse_only"
    audit.record(db, actor=actor, entity_type="study", entity_id=study.id, action="rollup_started",
                 reason=f"roll-up started ({trigger})", details={"trigger": trigger})
    return enqueue(db, study, actor, trigger)


def close_now(db: Session, actor: User, study_id: int, version: int, reason: str | None) -> int:
    """Survey Manager: roll up now — before every unit is in (a reason is required), or re-run a
    finished study's summary (a new version)."""
    if actor.role != Role.SURVEY_MANAGER:
        raise Forbidden("Only the Survey Manager closes a study")
    study = db.get(Study, study_id)
    if study is None:
        raise NotFound(f"study {study_id} not found")
    if study.status not in ("planned", "in_progress", "complete"):
        raise Conflict(f"This study is {study.status}")
    if _job_running(db, study):
        raise Conflict("A roll-up is already running for this study")
    open_units = db.scalar(select(func.count()).where(SurveyUnit.study_id == study.id, SurveyUnit.status != "submitted"))
    trigger = "rerun" if study.status == "complete" else "closed_early" if open_units else "all_units_submitted"
    if trigger != "all_units_submitted" and not (reason and reason.strip()):
        raise Unprocessable(f"{open_units} unit(s) are not submitted — give a reason to close now"
                            if open_units else "Give a reason to re-run the roll-up")
    update_versioned(db, Study, study.id, version, updated_at=text("now()"))
    audit.record(db, actor=actor, entity_type="study", entity_id=study.id, action="rollup_started",
                 reason=(reason or "").strip() or "all units submitted", details={"trigger": trigger, "open_units": open_units})
    return enqueue(db, study, actor, trigger)


def save(db: Session, study_id: int, result: dict, trigger: str, job_id: int | None) -> CatchmentSummary:
    study = db.get(Study, study_id)
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('study_rollup:' || :s))"), dict(s=str(study_id)))
    version = (db.scalar(select(func.max(CatchmentSummary.version)).where(CatchmentSummary.study_id == study_id)) or 0) + 1
    summary = CatchmentSummary(study_id=study_id, version=version, trigger=trigger, snapshot_id=study.snapshot_id,
                               config_version=str(load_config()["version"]), job_id=job_id, **result)
    db.add(summary)
    db.flush()
    if study.status != "complete":
        old = study.status
        update_versioned(db, Study, study.id, study.version, status="complete", updated_at=text("now()"))
        audit.record(db, actor=None, entity_type="study", entity_id=study.id, action="completed", from_state=old,
                     to_state="complete", reason=f"catchment summary v{version} ({trigger})",
                     details={"summary_id": summary.id, "confidence": result["confidence"], "facts_only": result["facts_only"]})
        p = db.get(Property, study.property_id)
        if p.stage in ("study_requested", "study_in_progress"):
            pipeline.study_transition(db, None, p, "study_complete", version=p.version,
                                      reason=f"catchment study #{study.id} complete (summary v{version}, {result['confidence']} confidence)",
                                      details={"study_id": study.id, "summary_id": summary.id})
    else:
        audit.record(db, actor=None, entity_type="study", entity_id=study.id, action="summary_rerun",
                     reason=f"catchment summary v{version} ({trigger})", details={"summary_id": summary.id})
    return summary
