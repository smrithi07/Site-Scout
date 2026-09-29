"""M3 survey units (docs/DESIGN.md §7 Unit generation): generate, edit, assign.

Invariant, re-validated after EVERY edit in the same transaction (a violation → 422, nothing saved):
  every to-survey segment of the study is in exactly one unit, no reused segment is in a unit,
  and no unit is empty.
All edits lock on the study's `version` (one plan, edited by one Survey Manager at a time; a stale
edit → 409) and are audited. Captured data is never touched by an edit or a reassignment.
"""
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import Role
from app.core.config import load_config
from app.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from app.core.locking import update_versioned
from app.models import Property, SegmentCapture, Study, StudySegment, SurveyUnit, User
from app.services import partition, pipeline

EDITABLE = ("planned", "in_progress")


def _cfg() -> dict:
    return load_config()["studies"]["units"]


def graph(db: Session, study: Study) -> list[dict]:
    """Every catchment segment (walkable), with junctions and a metric midpoint."""
    return [dict(r) for r in db.execute(text("""
        SELECT r.segment_id, r.from_node, r.to_node, r.length_m, ss.to_survey, ss.unit_id,
               ST_X(ST_Transform(ST_LineInterpolatePoint(r.geom, 0.5), 32644)) AS x,
               ST_Y(ST_Transform(ST_LineInterpolatePoint(r.geom, 0.5), 32644)) AS y
        FROM study_segments ss JOIN road_segments r ON r.snapshot_id = :s AND r.segment_id = ss.segment_id
        WHERE ss.study_id = :id"""), dict(s=study.snapshot_id, id=study.id)).mappings()]


def _require_sm(actor: User) -> None:
    if actor.role != Role.SURVEY_MANAGER:
        raise Forbidden("Only the Survey Manager edits and assigns survey units")


def _lock(db: Session, study_id: int, version: int, allowed=EDITABLE) -> Study:
    study = db.get(Study, study_id)
    if study is None:
        raise NotFound(f"study {study_id} not found")
    if study.status not in allowed:
        raise Conflict(f"This study is {study.status}; its units can't be changed")
    update_versioned(db, Study, study.id, version, updated_at=text("now()"))
    db.refresh(study)
    return study


def generate(db: Session, actor: User, study: Study, reason: str) -> list[SurveyUnit]:
    """(Re)build units from the study's to-survey segments. Only while no unit is assigned —
    after that the Survey Manager edits units instead of regenerating them."""
    if db.scalar(select(SurveyUnit.id).where(SurveyUnit.study_id == study.id, SurveyUnit.assignee_id.is_not(None)).limit(1)):
        raise Conflict("Units are already assigned; split, merge or move segments instead of regenerating")
    db.execute(update(StudySegment).where(StudySegment.study_id == study.id).values(unit_id=None))
    db.execute(delete(SurveyUnit).where(SurveyUnit.study_id == study.id))
    segs = graph(db, study)
    parts = partition.partition(segs, {s["segment_id"] for s in segs if s["to_survey"]}, _cfg())
    units = []
    for i, part in enumerate(parts, start=1):
        u = SurveyUnit(study_id=study.id, label=f"U{i}", segment_count=len(part["segment_ids"]),
                       **{k: part[k] for k in ("length_m", "minutes", "walk_minutes", "pieces")})
        db.add(u)
        db.flush()
        db.execute(update(StudySegment).where(StudySegment.study_id == study.id,
                                              StudySegment.segment_id.in_(part["segment_ids"])).values(unit_id=u.id))
        units.append(u)
    validate(db, study)
    audit.record(db, actor=actor, entity_type="study", entity_id=study.id, action="units_generated", reason=reason,
                 details={"units": len(units), "minutes": [u.minutes for u in units],
                          "pieces": [u.pieces for u in units]})
    return units


def regenerate(db: Session, actor: User, study_id: int, version: int, reason: str) -> list[SurveyUnit]:
    _require_sm(actor)
    return generate(db, actor, _lock(db, study_id, version, allowed=("planned",)), reason)


def validate(db: Session, study: Study) -> None:
    unassigned = db.scalar(select(func.count()).where(StudySegment.study_id == study.id, StudySegment.to_survey,
                                                     StudySegment.unit_id.is_(None)))
    stray = db.scalar(select(func.count()).where(StudySegment.study_id == study.id, ~StudySegment.to_survey,
                                                StudySegment.unit_id.is_not(None)))
    foreign = db.scalar(select(func.count()).select_from(StudySegment).join(SurveyUnit, SurveyUnit.id == StudySegment.unit_id)
                        .where(StudySegment.study_id == study.id, SurveyUnit.study_id != study.id))
    empty = db.scalar(select(func.count()).select_from(SurveyUnit).where(
        SurveyUnit.study_id == study.id,
        ~select(StudySegment.segment_id).where(StudySegment.unit_id == SurveyUnit.id).exists()))
    checks = ((unassigned, "to-survey segment(s) without a unit"), (stray, "reused segment(s) inside a unit"),
              (foreign, "segment(s) in another study's unit"), (empty, "empty unit(s)"))
    problems = [f"{n} {msg}" for n, msg in checks if n]
    if problems:
        raise Unprocessable("Unit plan invalid (one segment, one unit): " + "; ".join(problems))


def _refresh(db: Session, study: Study, unit_ids: set[int]) -> None:
    """Recompute the estimates of the units an edit touched; drop units the edit emptied."""
    segs = graph(db, study)
    adj = partition._graph(segs)
    for uid in unit_ids:
        members = [s for s in segs if s["unit_id"] == uid]
        u = db.get(SurveyUnit, uid)
        if not members:
            if u.assignee_id is not None:
                raise Conflict(f"{u.label} is assigned — unassign it before moving all its segments out")
            db.delete(u)
            continue
        est = partition.estimate(segs, members, _cfg(), adj)
        db.execute(update(SurveyUnit).where(SurveyUnit.id == uid).values(
            segment_count=len(members), updated_at=text("now()"), **est))
    db.flush()


def _unit(db: Session, study: Study, unit_id: int) -> SurveyUnit:
    u = db.get(SurveyUnit, unit_id)
    if u is None or u.study_id != study.id:
        raise NotFound(f"unit {unit_id} is not part of study {study.id}")
    if u.status == "submitted":
        raise Conflict(f"{u.label} is already submitted")
    return u


def _segments_of_study(db: Session, study: Study, segment_ids: list[str]) -> list[StudySegment]:
    rows = list(db.scalars(select(StudySegment).where(StudySegment.study_id == study.id,
                                                      StudySegment.segment_id.in_(segment_ids))))
    missing = set(segment_ids) - {r.segment_id for r in rows}
    if missing:
        raise Unprocessable(f"not in this study's catchment: {', '.join(sorted(missing)[:5])}")
    reused = [r.segment_id for r in rows if not r.to_survey]
    if reused:
        raise Unprocessable(f"reused (not to be surveyed) — can't be put in a unit: {', '.join(reused[:5])}")
    captured = db.scalars(select(SegmentCapture.segment_id).where(SegmentCapture.study_id == study.id,
                                                                SegmentCapture.segment_id.in_(segment_ids))).all()
    if captured:
        raise Conflict(f"already captured in this study, can't move: {', '.join(captured[:5])}")
    return rows


def move(db: Session, actor: User, study_id: int, version: int, segment_ids: list[str], to_unit_id: int) -> Study:
    _require_sm(actor)
    study = _lock(db, study_id, version)
    target = _unit(db, study, to_unit_id)
    rows = _segments_of_study(db, study, segment_ids)
    sources = {r.unit_id for r in rows} - {target.id}
    for uid in sources:
        _unit(db, study, uid)
    db.execute(update(StudySegment).where(StudySegment.study_id == study.id, StudySegment.segment_id.in_(segment_ids))
               .values(unit_id=target.id))
    _refresh(db, study, sources | {target.id})
    validate(db, study)
    audit.record(db, actor=actor, entity_type="study", entity_id=study.id, action="units_edited",
                 reason=f"moved {len(segment_ids)} segment(s) to {target.label}",
                 details={"op": "move", "segments": segment_ids, "to": target.id, "from": sorted(sources)})
    return study


def split(db: Session, actor: User, study_id: int, version: int, unit_id: int, segment_ids: list[str]) -> Study:
    _require_sm(actor)
    study = _lock(db, study_id, version)
    src = _unit(db, study, unit_id)
    rows = _segments_of_study(db, study, segment_ids)
    if any(r.unit_id != src.id for r in rows):
        raise Unprocessable(f"all segments to split off must belong to {src.label}")
    if len(rows) >= src.segment_count:
        raise Unprocessable("a split must leave segments in both units")
    n = db.scalar(select(func.count()).where(SurveyUnit.study_id == study.id))
    new = SurveyUnit(study_id=study.id, label=_next_label(db, study, n))
    db.add(new)
    db.flush()
    db.execute(update(StudySegment).where(StudySegment.study_id == study.id, StudySegment.segment_id.in_(segment_ids))
               .values(unit_id=new.id))
    _refresh(db, study, {src.id, new.id})
    validate(db, study)
    audit.record(db, actor=actor, entity_type="study", entity_id=study.id, action="units_edited",
                 reason=f"split {len(segment_ids)} segment(s) off {src.label} into {new.label}",
                 details={"op": "split", "from": src.id, "new": new.id, "segments": segment_ids})
    return study


def merge(db: Session, actor: User, study_id: int, version: int, unit_ids: list[int]) -> Study:
    _require_sm(actor)
    if len(set(unit_ids)) < 2:
        raise Unprocessable("merge needs at least two different units")
    study = _lock(db, study_id, version)
    keep, *others = [_unit(db, study, uid) for uid in unit_ids]
    people = {u.assignee_id for u in (keep, *others) if u.assignee_id is not None}
    if len(people) > 1:
        raise Conflict("These units are assigned to different executives — unassign one first")
    db.execute(update(StudySegment).where(StudySegment.unit_id.in_([u.id for u in others])).values(unit_id=keep.id))
    for u in others:
        db.delete(u)
    if people and keep.assignee_id is None:
        keep.assignee_id, keep.status = people.pop(), "assigned"
    db.flush()
    _refresh(db, study, {keep.id})
    validate(db, study)
    audit.record(db, actor=actor, entity_type="study", entity_id=study.id, action="units_edited",
                 reason=f"merged {', '.join(u.label for u in others)} into {keep.label}",
                 details={"op": "merge", "into": keep.id, "merged": [u.id for u in others]})
    return study


def assign(db: Session, actor: User, study_id: int, version: int, unit_id: int, assignee_id: int | None) -> Study:
    """Assign (or reassign / unassign) a unit. The first assignment starts the study; captured data
    stays with the segment whoever captured it."""
    _require_sm(actor)
    study = _lock(db, study_id, version)
    u = _unit(db, study, unit_id)
    old = u.assignee_id
    if assignee_id is not None:
        person = db.get(User, assignee_id)
        if person is None or person.role != Role.SURVEY_EXECUTIVE:
            raise Unprocessable("Units are assigned to survey executives")
    elif db.scalar(select(SegmentCapture.id).where(SegmentCapture.unit_id == u.id).limit(1)):
        raise Conflict(f"{u.label} already has captures; reassign it instead of unassigning")
    u.assignee_id = assignee_id
    u.status = "assigned" if assignee_id else "draft"
    u.assigned_at = func.now() if assignee_id else None
    db.flush()
    if study.status == "planned" and assignee_id is not None:
        update_versioned(db, Study, study.id, study.version, status="in_progress", updated_at=text("now()"))
        audit.record(db, actor=actor, entity_type="study", entity_id=study.id, action="started", from_state="planned",
                     to_state="in_progress", reason=f"first unit assigned ({u.label})")
        p = db.get(Property, study.property_id)
        if p.stage == "study_requested":
            pipeline.study_transition(db, actor, p, "study_in_progress", version=p.version,
                                      reason=f"survey of study #{study.id} started", details={"study_id": study.id})
    action = "unit_assigned" if assignee_id and not old else "unit_reassigned" if assignee_id else "unit_unassigned"
    audit.record(db, actor=actor, entity_type="study", entity_id=study.id, action=action,
                 reason=f"{u.label}: {old or '—'} → {assignee_id or '—'}",
                 details={"unit_id": u.id, "from": old, "to": assignee_id, "captures_kept": True})
    db.refresh(study)
    return study


def _next_label(db: Session, study: Study, n: int) -> str:
    used = set(db.scalars(select(SurveyUnit.label).where(SurveyUnit.study_id == study.id)))
    i = n + 1
    while f"U{i}" in used:
        i += 1
    return f"U{i}"


def units_of(db: Session, study_id: int) -> list[SurveyUnit]:
    return list(db.scalars(select(SurveyUnit).where(SurveyUnit.study_id == study_id).order_by(SurveyUnit.id)))


def progress(db: Session, study_id: int) -> dict[int, dict]:
    """Per unit: lanes captured in THIS study (surveyed / could not survey). A lane counts once,
    by its latest capture."""
    rows = db.execute(text("""
        SELECT ss.unit_id, count(*) FILTER (WHERE c.status = 'surveyed') AS surveyed,
               count(*) FILTER (WHERE c.status = 'could_not_survey') AS gaps
        FROM study_segments ss
        JOIN LATERAL (SELECT status FROM segment_captures c WHERE c.study_id = ss.study_id
                      AND c.segment_id = ss.segment_id ORDER BY c.captured_at DESC LIMIT 1) c ON true
        WHERE ss.study_id = :s AND ss.unit_id IS NOT NULL GROUP BY ss.unit_id"""), dict(s=study_id)).mappings()
    return {r["unit_id"]: {"surveyed": r["surveyed"], "gaps": r["gaps"]} for r in rows}


def summary(db: Session, study_id: int) -> dict:
    units = units_of(db, study_id)
    mins = [u.minutes for u in units]
    prog = progress(db, study_id)
    handled = sum(p["surveyed"] + p["gaps"] for p in prog.values())
    lanes = sum(u.segment_count for u in units)
    return {"count": len(units), "assigned": sum(u.assignee_id is not None for u in units),
            "minutes_min": min(mins, default=None), "minutes_max": max(mins, default=None),
            "total_minutes": round(sum(mins), 1), "lanes": lanes, "handled": handled,
            "surveyed": sum(p["surveyed"] for p in prog.values()), "gaps": sum(p["gaps"] for p in prog.values()),
            "progress_pct": round(100 * handled / lanes, 1) if lanes else None}


def mine(db: Session, user: User) -> list[SurveyUnit]:
    return list(db.scalars(select(SurveyUnit).join(Study, Study.id == SurveyUnit.study_id)
                           .where(SurveyUnit.assignee_id == user.id, Study.status == "in_progress")
                           .order_by(SurveyUnit.id)))


def visible_unit(db: Session, user: User, unit_id: int) -> SurveyUnit:
    u = db.get(SurveyUnit, unit_id)
    if u is None:
        raise NotFound(f"unit {unit_id} not found")
    if user.role == Role.SURVEY_MANAGER or (user.role == Role.SURVEY_EXECUTIVE and u.assignee_id == user.id):
        return u
    raise Forbidden("This unit isn't assigned to you")


def unit_geojson(db: Session, u: SurveyUnit) -> dict:
    """The unit's lanes in walking order (the same route its time estimate assumes)."""
    study = db.get(Study, u.study_id)
    segs = graph(db, study)
    order, _ = partition.walk(segs, [s for s in segs if s["unit_id"] == u.id])
    rank = {s["segment_id"]: i for i, s in enumerate(order)}
    rows = db.execute(text("""
        SELECT ss.segment_id, r.name, r.highway, r.length_m, ST_AsGeoJSON(r.geom, 6)::json AS geometry,
               EXISTS (SELECT 1 FROM segment_captures c WHERE c.study_id = :st AND c.segment_id = ss.segment_id) AS captured
        FROM study_segments ss JOIN road_segments r ON r.snapshot_id = :s AND r.segment_id = ss.segment_id
        WHERE ss.unit_id = :u"""), dict(s=study.snapshot_id, st=study.id, u=u.id)).mappings()
    rows = list(rows)
    from app.services.captures import lane_status  # local: captures imports this module
    latest = lane_status(db, study.id, [r["segment_id"] for r in rows])
    return {"type": "FeatureCollection", "features": sorted((
        {"type": "Feature", "geometry": r["geometry"],
         "properties": {**{k: r[k] for k in ("segment_id", "name", "highway", "length_m", "captured")},
                        "order": rank[r["segment_id"]] + 1,
                        "capture": ({k: latest[r["segment_id"]][k] for k in ("status", "reason", "time_band", "gps_distance_m")}
                                    if r["segment_id"] in latest else None)}} for r in rows),
        key=lambda f: f["properties"]["order"])}
