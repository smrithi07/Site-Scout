"""M3 lane capture (docs/DESIGN.md §7 Lane capture). One form per lane, raw observations only.

- Only the unit's assignee captures, only lanes of that unit, only while the study is in progress
  and the unit isn't submitted. The Survey Manager cannot capture.
- Idempotent by the phone's client id (Core rule 6): a retried submit returns the saved capture.
- "Could not survey" needs a reason and carries no observations; it counts as handled, not covered.
- A lane can be captured again before the unit is submitted (a correction); captures are
  append-only, so the latest one counts and the earlier one stays on record.
- Time: the device's capture time is kept (offline drafts are submitted later) and checked against
  the server clock; the time band is stamped from it, never typed. GPS is required; its distance to
  the lane is computed here and flagged when far, never silently trusted.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import Role
from app.core.config import load_config
from app.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from app.models import SegmentCapture, Study, StudySegment, SurveyUnit, User
from app.services import rollup, units
from app.services.studies import time_band


def _cfg() -> dict:
    return load_config()["studies"]["capture"]


def _unit_for_capture(db: Session, user: User, unit_id: int) -> tuple[SurveyUnit, Study]:
    if user.role != Role.SURVEY_EXECUTIVE:
        raise Forbidden("Only survey executives capture lane data")
    u = db.get(SurveyUnit, unit_id)
    if u is None:
        raise NotFound(f"unit {unit_id} not found")
    if u.assignee_id != user.id:
        raise Forbidden("This unit isn't assigned to you")
    study = db.get(Study, u.study_id)
    if study.status != "in_progress":
        raise Conflict(f"This study is {study.status}; captures are closed")
    return u, study


def _check_time(at: datetime | None) -> datetime:
    now = datetime.now(timezone.utc)
    if at is None:
        return now
    if at.tzinfo is None:
        raise Unprocessable("captured_at needs a timezone")
    cfg = _cfg()
    if at > now + timedelta(minutes=cfg["max_future_skew_minutes"]):
        raise Unprocessable("captured_at is in the future — check the phone's clock")
    if at < now - timedelta(days=cfg["max_backdate_days"]):
        raise Unprocessable(f"This draft is older than {cfg['max_backdate_days']} days — survey the lane again")
    return at


def capture(db: Session, user: User, body) -> tuple[SegmentCapture, bool, list[dict]]:
    """Returns (capture, created, warnings)."""
    existing = db.scalar(select(SegmentCapture).where(SegmentCapture.client_id == str(body.client_id)))
    if existing is not None:                      # a retried submit: same answer, nothing new
        if existing.captured_by != user.id:
            raise Conflict("This client id was already used by someone else")
        return existing, False, []
    u, study = _unit_for_capture(db, user, body.unit_id)
    if u.status == "submitted":
        raise Conflict(f"{u.label} is already submitted; ask the Survey Manager to reopen it")
    lane = db.scalar(select(StudySegment).where(StudySegment.study_id == study.id,
                                                StudySegment.segment_id == body.segment_id))
    if lane is None or lane.unit_id != u.id:
        raise Unprocessable(f"lane {body.segment_id} is not part of {u.label}")
    at = _check_time(body.captured_at)
    gps = db.execute(text("""
        SELECT ST_Distance(r.geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) AS d,
               ST_AsEWKT(r.geom) AS ewkt
        FROM road_segments r WHERE r.snapshot_id = :s AND r.segment_id = :g"""),
        dict(lat=body.lat, lon=body.lon, s=study.snapshot_id, g=body.segment_id)).one()
    previous = db.scalar(select(func.count()).select_from(SegmentCapture).where(
        SegmentCapture.study_id == study.id, SegmentCapture.segment_id == body.segment_id))
    c = SegmentCapture(client_id=str(body.client_id), study_id=study.id, unit_id=u.id, snapshot_id=study.snapshot_id,
                       segment_id=body.segment_id, geom=gps.ewkt, captured_by=user.id, source="field",
                       status=body.status, reason=(body.reason or "").strip() or None, captured_at=at,
                       time_band=time_band(at), lat=body.lat, lon=body.lon, gps_accuracy_m=body.gps_accuracy_m,
                       gps_distance_m=round(gps.d, 1),
                       observations=body.observations.model_dump() if body.observations else {},
                       notes=(body.notes or "").strip() or None)
    db.add(c)
    if u.status == "assigned":
        u.status = "in_progress"
    db.flush()
    warnings = []
    if gps.d > _cfg()["gps_max_distance_m"]:
        warnings.append({"code": "gps_far", "message": f"Your location was {gps.d:.0f} m from this lane — saved, and "
                                                       "flagged for the Survey Manager."})
    if previous:
        audit.record(db, actor=user, entity_type="study", entity_id=study.id, action="lane_recaptured",
                     reason=f"{u.label}: lane {body.segment_id} captured again ({body.status})",
                     details={"unit_id": u.id, "segment_id": body.segment_id, "capture_id": c.id})
    return c, True, warnings


def submit_unit(db: Session, user: User, unit_id: int) -> SurveyUnit:
    """All lanes handled (surveyed or could-not-survey) → submitted. Idempotent."""
    u, study = _unit_for_capture(db, user, unit_id)
    if u.status == "submitted":
        return u
    prog = units.progress(db, study.id).get(u.id, {"surveyed": 0, "gaps": 0})
    left = u.segment_count - prog["surveyed"] - prog["gaps"]
    if left:
        raise Conflict(f"{left} lane(s) of {u.label} still need a capture (surveyed or could not survey)")
    db.execute(update(SurveyUnit).where(SurveyUnit.id == u.id).values(status="submitted", updated_at=text("now()")))
    audit.record(db, actor=user, entity_type="study", entity_id=study.id, action="unit_submitted",
                 reason=f"{u.label} submitted: {prog['surveyed']} surveyed, {prog['gaps']} could not survey",
                 details={"unit_id": u.id, **prog})
    db.flush()
    rollup.maybe_start(db, study, user)          # the last unit in → roll-up job
    db.refresh(u)
    return u


def lane_status(db: Session, study_id: int, segment_ids: list[str]) -> dict[str, dict]:
    """Latest capture per lane in this study (what counts)."""
    rows = db.execute(text("""
        SELECT DISTINCT ON (segment_id) segment_id, status, reason, captured_at, time_band, gps_distance_m
        FROM segment_captures WHERE study_id = :s AND segment_id = ANY(:ids)
        ORDER BY segment_id, captured_at DESC"""), dict(s=study_id, ids=segment_ids)).mappings()
    return {r["segment_id"]: dict(r) for r in rows}
