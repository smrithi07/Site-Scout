"""M3 study request + reuse (docs/DESIGN.md §7).

Catchment: road segments whose midpoint lies within `studies.catchment_radius_m` of the property.

Reuse, per segment, from its captures (freshness is per segment capture, never per study):
  fresh      — a `surveyed` capture within `freshness_days` → reusable, counts as covered
  fresh_gap  — only a recent `could_not_survey` → handled, NOT covered, not retried until stale
  stale      — captured before, but nothing fresh → must be surveyed again; never reused
  uncovered  — never captured
Coverage is length-weighted: fresh length / catchment length.

Modes (what gets surveyed):
  reuse_and_fill (default) — reuse fresh segments, survey stale + uncovered
  reuse_only               — survey nothing; the summary gets a lower-confidence label
  full_survey              — waive reuse, survey every segment
Any non-default mode is an override and needs a reason. The BD Manager chooses at request time;
the Survey Manager has the final say at planning time (a change needs a reason; so does
reuse_only below the coverage threshold). Everything is audited. Stale data is never reused,
whatever the mode.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import insert, select, text, update
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import Role
from app.core.config import load_config
from app.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from app.core.locking import update_versioned
from app.models import Property, Study, StudySegment, User
from app.services import pipeline
from app.services.snapshots import active_snapshot

MODES = ("reuse_and_fill", "reuse_only", "full_survey")
DEFAULT_MODE = "reuse_and_fill"
OPEN = ("requested", "planned", "in_progress")
STATES = ("fresh", "fresh_gap", "stale", "uncovered")
IST = ZoneInfo("Asia/Kolkata")


def time_band(at: datetime) -> str:
    """Auto-stamped on every capture (footfall varies by time of day). IST hours."""
    h = at.astimezone(IST).hour
    return "morning" if 6 <= h < 11 else "midday" if 11 <= h < 16 else "evening" if 16 <= h < 21 else "night"


def _cfg() -> dict:
    return load_config()["studies"]


def catchment_segments(db: Session, snapshot_id: int, lat: float, lon: float, radius_m: float) -> list[dict]:
    # Bounding-box prefilter on the GiST index first (1.3 s → ~40 ms), then the exact midpoint test.
    return [dict(r) for r in db.execute(text("""
        WITH pt AS (SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) AS g)
        SELECT s.segment_id, s.length_m
        FROM road_segments s, pt
        WHERE s.snapshot_id = :s
          AND s.geom && ST_Expand(pt.g, :deg)
          AND ST_DWithin(ST_LineInterpolatePoint(s.geom, 0.5)::geography, pt.g::geography, :r)
        ORDER BY s.segment_id"""),
        dict(s=snapshot_id, lat=lat, lon=lon, r=radius_m, deg=radius_m / 90_000)).mappings()]


# A capture belongs to a catchment segment if the ids match AND it was made on the same snapshot
# or the segment's geometry is unchanged since (ids are only stable within a snapshot).
# 32644 = UTM zone 44N, metres for Chennai.
_MATCH = """c.segment_id = seg.segment_id AND (c.snapshot_id = :s OR
            ST_HausdorffDistance(ST_Transform(c.geom, 32644), ST_Transform(seg.geom, 32644)) <= :tol)"""


def reuse_check(db: Session, snapshot_id: int, segment_ids: list[str]) -> list[dict]:
    cfg = _cfg()
    rows = db.execute(text(f"""
        WITH seg AS (SELECT segment_id, length_m, geom FROM road_segments
                     WHERE snapshot_id = :s AND segment_id = ANY(:ids))
        SELECT seg.segment_id, seg.length_m, f.id AS fresh_id, f.age AS fresh_age, g.id AS gap_id,
               o.id AS old_id, o.age AS old_age
        FROM seg
        LEFT JOIN LATERAL (
            SELECT c.id, (extract(epoch FROM now() - c.captured_at) / 86400)::float8 AS age FROM segment_captures c
            WHERE {_MATCH} AND c.status = 'surveyed' AND c.captured_at >= now() - make_interval(days => :fd)
            ORDER BY c.captured_at DESC LIMIT 1) f ON true
        LEFT JOIN LATERAL (
            SELECT c.id FROM segment_captures c
            WHERE {_MATCH} AND c.status = 'could_not_survey' AND c.captured_at >= now() - make_interval(days => :fd)
            ORDER BY c.captured_at DESC LIMIT 1) g ON true
        LEFT JOIN LATERAL (
            SELECT c.id, (extract(epoch FROM now() - c.captured_at) / 86400)::float8 AS age FROM segment_captures c
            WHERE {_MATCH} AND c.captured_at < now() - make_interval(days => :fd)
            ORDER BY c.captured_at DESC LIMIT 1) o ON true"""),
        dict(s=snapshot_id, ids=segment_ids, fd=cfg["freshness_days"], tol=cfg["cross_snapshot_match_m"])).mappings()
    out = []
    for r in rows:
        state = "fresh" if r["fresh_id"] else "fresh_gap" if r["gap_id"] else "stale" if r["old_id"] else "uncovered"
        out.append({"segment_id": r["segment_id"], "length_m": r["length_m"], "reuse_state": state,
                    "reused_capture_id": r["fresh_id"],
                    "capture_age_days": r["fresh_age"] if state == "fresh" else r["old_age"] if state == "stale" else None})
    return out


def summarise(segments: list[dict]) -> dict:
    cfg = _cfg()
    total = sum(s["length_m"] for s in segments) or 1.0
    length = {k: sum(s["length_m"] for s in segments if s["reuse_state"] == k) for k in STATES}
    count = {k: sum(1 for s in segments if s["reuse_state"] == k) for k in STATES}
    pct = {k: round(100 * v / total, 1) for k, v in length.items()}
    ages = [s["capture_age_days"] for s in segments if s["reuse_state"] == "fresh"]
    coverage = length["fresh"] / total
    message = (f"{pct['fresh']:g}% covered by fresh survey data · "
               f"{round(pct['stale'] + pct['uncovered'], 1):g}% requires new survey")
    if count["fresh_gap"]:
        message += f" · {pct['fresh_gap']:g}% could not be surveyed recently (not retried until stale)"
    return {"coverage": round(coverage, 4), "coverage_pct": pct["fresh"], "pct": pct,
            "length_m": {k: round(v) for k, v in length.items()}, "counts": count,
            "oldest_reused_days": round(max(ages), 1) if ages else None,
            "freshness_days": cfg["freshness_days"], "threshold": cfg["reuse_default_min_coverage"],
            "meets_threshold": coverage >= cfg["reuse_default_min_coverage"], "message": message,
            "checked_at": datetime.now(timezone.utc).isoformat()}


def to_survey(state: str, mode: str) -> bool:
    if mode == "full_survey":
        return True
    if mode == "reuse_only":
        return False
    return state in ("stale", "uncovered")


def _check_mode(mode: str, reason: str | None, summary: dict, needs_reason: bool, who: str) -> None:
    if mode not in MODES:
        raise Unprocessable(f"unknown reuse mode {mode!r}; one of {', '.join(MODES)}")
    if mode == "reuse_only" and summary["counts"]["fresh"] == 0:
        raise Unprocessable("reuse_only: there is no fresh survey data in this catchment to reuse")
    if needs_reason and not (reason and reason.strip()):
        extra = (f" (fresh coverage {summary['coverage_pct']:g}% is below "
                 f"{summary['threshold'] * 100:g}%)" if mode == "reuse_only" and not summary["meets_threshold"] else "")
        raise Unprocessable(f"{who}: '{mode}' is an override{extra} — give a reason")


def preview(db: Session, p: Property) -> dict:
    """What a request would find, without writing anything (the BD Manager's request dialog)."""
    snap = active_snapshot(db)
    radius = _cfg()["catchment_radius_m"]
    segs = reuse_check(db, snap.id, [s["segment_id"] for s in catchment_segments(db, snap.id, p.lat, p.lon, radius)])
    return {"property_id": p.id, "radius_m": radius, "segment_count": len(segs),
            "total_length_m": round(sum(s["length_m"] for s in segs)), "reuse": summarise(segs),
            "default_mode": DEFAULT_MODE, "modes": list(MODES)}


def request(db: Session, actor: User, property_id: int, version: int, mode: str, reason: str | None) -> Study:
    if actor.role != Role.BD_MANAGER:
        raise Forbidden("Only the BD Manager requests catchment studies")
    p = db.get(Property, property_id)
    if p is None:
        raise NotFound(f"property {property_id} not found")
    if p.status == "merged":
        raise Conflict("This entry was merged into another property; request the study on that one")
    allowed = _cfg()["request_from_stages"]
    if p.stage not in allowed:
        raise Conflict(f"A study can be requested from {', '.join(allowed)}; this property is {p.stage}")
    if db.scalar(select(Study.id).where(Study.property_id == p.id, Study.status.in_(OPEN))):
        raise Conflict("This property already has an open study")
    snap = active_snapshot(db)
    radius = _cfg()["catchment_radius_m"]
    segs = reuse_check(db, snap.id, [s["segment_id"] for s in catchment_segments(db, snap.id, p.lat, p.lon, radius)])
    if not segs:
        raise Unprocessable(f"No surveyable road segments within {radius:g} m of this property")
    summary = summarise(segs)
    _check_mode(mode, reason, summary, needs_reason=mode != DEFAULT_MODE, who="BD Manager")

    catchment = db.scalar(text("SELECT ST_AsEWKT(ST_Buffer(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,"
                               " :r, 'quad_segs=16')::geometry)"), dict(lat=p.lat, lon=p.lon, r=radius))
    study = Study(property_id=p.id, requested_by=actor.id, snapshot_id=snap.id,
                  config_version=str(load_config()["version"]), lat=p.lat, lon=p.lon, radius_m=radius,
                  catchment=catchment, segment_count=len(segs), total_length_m=sum(s["length_m"] for s in segs),
                  reuse=summary, requested_mode=mode, request_reason=(reason or "").strip() or None)
    db.add(study)
    db.flush()
    db.execute(insert(StudySegment), [{**s, "study_id": study.id, "to_survey": to_survey(s["reuse_state"], mode)}
                                      for s in segs])
    pipeline.study_transition(db, actor, p, "study_requested", version=version,
                              reason=f"catchment study #{study.id} requested ({mode})"
                                     + (f": {reason.strip()}" if reason and reason.strip() else ""),
                              details={"study_id": study.id})
    audit.record(db, actor=actor, entity_type="study", entity_id=study.id, action="requested", to_state="requested",
                 reason=(reason or "").strip() or f"requested with the default reuse mode ({mode})",
                 details={"property_id": p.id, "mode": mode, "override": mode != DEFAULT_MODE,
                          "coverage_pct": summary["coverage_pct"], "message": summary["message"]})
    db.flush()
    db.refresh(study)
    return study


def plan(db: Session, actor: User, study_id: int, version: int, mode: str, reason: str | None) -> Study:
    """The Survey Manager's final reuse decision. Coverage is re-checked now: captures may have gone
    stale (or new ones arrived) since the request."""
    if actor.role != Role.SURVEY_MANAGER:
        raise Forbidden("Only the Survey Manager plans studies")
    study = _get(db, study_id)
    if study.status not in ("requested", "planned"):
        raise Conflict(f"This study is {study.status}; its plan can no longer change")
    segs = reuse_check(db, study.snapshot_id, list(db.scalars(select(StudySegment.segment_id)
                                                                .where(StudySegment.study_id == study.id))))
    summary = summarise(segs)
    needs_reason = mode != study.requested_mode or (mode == "reuse_only" and not summary["meets_threshold"])
    _check_mode(mode, reason, summary, needs_reason=needs_reason, who="Survey Manager")
    old = study.status
    update_versioned(db, Study, study.id, version, status="planned", planned_mode=mode,
                     plan_reason=(reason or "").strip() or None, planned_by=actor.id, planned_at=text("now()"),
                     reuse=summary, updated_at=text("now()"))
    for s in segs:
        db.execute(update(StudySegment).where(StudySegment.study_id == study.id, StudySegment.segment_id == s["segment_id"])
                   .values(reuse_state=s["reuse_state"], reused_capture_id=s["reused_capture_id"],
                           capture_age_days=s["capture_age_days"], to_survey=to_survey(s["reuse_state"], mode)))
    audit.record(db, actor=actor, entity_type="study", entity_id=study.id, action="planned", from_state=old,
                 to_state="planned",
                 reason=(reason or "").strip() or f"confirmed the requested reuse mode ({mode})",
                 details={"mode": mode, "requested_mode": study.requested_mode, "override": needs_reason,
                          "coverage_pct": summary["coverage_pct"], "message": summary["message"],
                          "to_survey": sum(to_survey(s["reuse_state"], mode) for s in segs)})
    db.flush()
    db.refresh(study)
    return study


def cancel(db: Session, actor: User, study_id: int, version: int, reason: str) -> Study:
    """BD Manager withdraws the study; the property goes back to shortlisted. Captured data stays."""
    if actor.role != Role.BD_MANAGER:
        raise Forbidden("Only the BD Manager cancels a study")
    study = _get(db, study_id)
    if study.status not in OPEN:
        raise Conflict(f"This study is already {study.status}")
    _cancel(db, actor, study, reason, version)
    p = db.get(Property, study.property_id)
    if p.stage in pipeline.STUDY_STAGES:
        pipeline.study_transition(db, actor, p, "shortlisted", version=p.version,
                                  reason=f"study #{study.id} cancelled: {reason}", details={"study_id": study.id})
    db.flush()
    db.refresh(study)
    return study


def cancel_open_for_property(db: Session, actor: User, property_id: int, reason: str) -> None:
    """The property left the study stages (rejected / on hold): cancel the study, keep its data."""
    study = db.scalar(select(Study).where(Study.property_id == property_id, Study.status.in_(OPEN)))
    if study is not None:
        _cancel(db, actor, study, reason, study.version)


def _cancel(db: Session, actor: User, study: Study, reason: str, version: int) -> None:
    old = study.status
    update_versioned(db, Study, study.id, version, status="cancelled", cancel_reason=reason, updated_at=text("now()"))
    audit.record(db, actor=actor, entity_type="study", entity_id=study.id, action="cancelled", from_state=old,
                 to_state="cancelled", reason=reason, details={"captures_kept": True})


def _get(db: Session, study_id: int) -> Study:
    study = db.get(Study, study_id)
    if study is None:
        raise NotFound(f"study {study_id} not found")
    return study


def visible(db: Session, user: User, study_id: int) -> Study:
    if user.role not in (Role.BD_MANAGER, Role.SURVEY_MANAGER):
        raise Forbidden("Studies are visible to the BD Manager and the Survey Manager")
    return _get(db, study_id)


def list_for(db: Session, user: User, status: str | None = None) -> list[Study]:
    if user.role not in (Role.BD_MANAGER, Role.SURVEY_MANAGER):
        return []
    q = select(Study).order_by(Study.id.desc())
    if status:
        q = q.where(Study.status == status)
    return list(db.scalars(q))


def segments_geojson(db: Session, study: Study) -> dict:
    rows = db.execute(text("""
        SELECT ss.segment_id, ss.length_m, ss.reuse_state, ss.capture_age_days, ss.to_survey, ss.unit_id,
               r.name, r.highway, ST_AsGeoJSON(r.geom, 6)::json AS geometry
        FROM study_segments ss JOIN road_segments r ON r.snapshot_id = :s AND r.segment_id = ss.segment_id
        WHERE ss.study_id = :id ORDER BY ss.segment_id"""), dict(s=study.snapshot_id, id=study.id)).mappings()
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": r["geometry"],
         "properties": {k: r[k] for k in ("segment_id", "length_m", "reuse_state", "capture_age_days", "to_survey",
                                          "unit_id", "name", "highway")}} for r in rows]}
