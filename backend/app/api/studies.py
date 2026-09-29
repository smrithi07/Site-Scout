"""M3 catchment studies: request (BD Manager), inbox + planning (Survey Manager). Thin: rules live
in `services/studies.py`, masking in `schemas/` (the property goes through the per-role builder)."""
from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import Role, require_roles
from app.core.db import get_db
from app.core.errors import NotFound
from app.models import CatchmentSummary, Job, Property, Study, StudySegment, User
from app.schemas.properties import property_response
from app.schemas.studies import (
    CancelStudy,
    CaptureIn,
    CloseStudy,
    PlanDecision,
    Regenerate,
    StudyRequest,
    UnitAssign,
    UnitMerge,
    UnitMove,
    UnitSplit,
    study_response,
    summary_response,
    unit_response,
)
from app.services import captures, properties, rollup, studies, units

router = APIRouter(prefix="/studies", tags=["studies"])
unit_router = APIRouter(tags=["studies"])
managers = require_roles(Role.BD_MANAGER, Role.SURVEY_MANAGER)
survey_manager = require_roles(Role.SURVEY_MANAGER)


def _out(db: Session, study, user: User) -> dict:
    count, length = db.execute(select(func.count(), func.coalesce(func.sum(StudySegment.length_m), 0))
                               .where(StudySegment.study_id == study.id, StudySegment.to_survey)).one()
    out = study_response(study, db.get(Property, study.property_id), user.role,
                         survey={"segments": count, "length_m": round(length)})
    out["units"] = units.summary(db, study.id)        # BD Manager: status only; the unit map is the Survey Manager's
    job = db.get(Job, study.rollup_job_id) if study.rollup_job_id else None
    out["rollup_job"] = {"id": job.id, "status": job.status, "error": job.error} if job else None
    latest = _latest_summary(db, study.id)
    out["summary"] = ({k: getattr(latest, k) for k in ("id", "version", "confidence", "facts_only", "created_at")}
                      if latest else None)
    return out


def _latest_summary(db: Session, study_id: int):
    return db.scalar(select(CatchmentSummary).where(CatchmentSummary.study_id == study_id)
                     .order_by(CatchmentSummary.version.desc()).limit(1))


@router.get("/preview")
def preview(property_id: int, user: User = Depends(require_roles(Role.BD_MANAGER)), db: Session = Depends(get_db)) -> dict:
    """Coverage and reuse options before requesting — nothing is written."""
    return studies.preview(db, properties.visible(db, user, property_id))


@router.post("", status_code=201)
def request_study(body: StudyRequest, user: User = Depends(require_roles(Role.BD_MANAGER)),
                  db: Session = Depends(get_db)) -> dict:
    study = studies.request(db, user, body.property_id, body.version, body.mode, body.reason)
    db.commit()
    return _out(db, study, user)


@router.get("")
def list_studies(status: str | None = None, property_id: int | None = None, user: User = Depends(managers),
                 db: Session = Depends(get_db)) -> list[dict]:
    return [_out(db, s, user) for s in studies.list_for(db, user, status, property_id)]


@router.get("/{study_id}")
def get_study(study_id: int, user: User = Depends(managers), db: Session = Depends(get_db)) -> dict:
    return _out(db, studies.visible(db, user, study_id), user)


@router.get("/{study_id}/segments")
def study_segments(study_id: int, user: User = Depends(require_roles(Role.SURVEY_MANAGER)),
                   db: Session = Depends(get_db)) -> dict:
    """The catchment's road segments with reuse state — the Survey Manager's planning map."""
    return studies.segments_geojson(db, studies.visible(db, user, study_id))


@router.post("/{study_id}/plan")
def plan_study(study_id: int, body: PlanDecision, user: User = Depends(require_roles(Role.SURVEY_MANAGER)),
               db: Session = Depends(get_db)) -> dict:
    study = studies.plan(db, user, study_id, body.version, body.mode, body.reason)
    db.commit()
    return _out(db, study, user)


@router.post("/{study_id}/cancel")
def cancel_study(study_id: int, body: CancelStudy, user: User = Depends(require_roles(Role.BD_MANAGER)),
                 db: Session = Depends(get_db)) -> dict:
    study = studies.cancel(db, user, study_id, body.version, body.reason)
    db.commit()
    return _out(db, study, user)


# --- roll-up → Catchment Summary ----------------------------------------------------------

@router.post("/{study_id}/rollup", status_code=202)
def close_study(study_id: int, body: CloseStudy, user: User = Depends(require_roles(Role.SURVEY_MANAGER)),
                db: Session = Depends(get_db)) -> dict:
    """Roll up now: before every unit is in (reason required), or re-run into a new summary version."""
    job_id = rollup.close_now(db, user, study_id, body.version, body.reason)
    db.commit()
    return {"job_id": job_id}


@router.get("/{study_id}/summary")
def latest_summary(study_id: int, version: int | None = None, user: User = Depends(managers),
                   db: Session = Depends(get_db)) -> dict:
    studies.visible(db, user, study_id)
    s = (db.scalar(select(CatchmentSummary).where(CatchmentSummary.study_id == study_id, CatchmentSummary.version == version))
         if version else _latest_summary(db, study_id))
    if s is None:
        raise NotFound(f"no catchment summary{f' v{version}' if version else ''} for study {study_id} yet")
    out = summary_response(s)
    out["versions"] = [v for (v,) in db.execute(select(CatchmentSummary.version).where(CatchmentSummary.study_id == study_id)
                                               .order_by(CatchmentSummary.version.desc()))]
    return out


# --- survey units (Survey Manager edits/assigns; each edit re-validates one-segment-one-unit) ---

def _plan(db: Session, study_id: int, user: User) -> dict:
    db.commit()
    study = db.get(Study, study_id)
    names = dict(db.execute(select(User.id, User.name)).all())
    prog = units.progress(db, study_id)
    return {"study": _out(db, study, user),
            "units": [unit_response(u, {"assignee_name": names.get(u.assignee_id),
                                        **prog.get(u.id, {"surveyed": 0, "gaps": 0})})
                      for u in units.units_of(db, study_id)]}


@router.get("/{study_id}/units")
def list_units(study_id: int, user: User = Depends(survey_manager), db: Session = Depends(get_db)) -> dict:
    studies.visible(db, user, study_id)
    return _plan(db, study_id, user)


@router.post("/{study_id}/units/generate")
def regenerate(study_id: int, body: Regenerate, user: User = Depends(survey_manager), db: Session = Depends(get_db)) -> dict:
    units.regenerate(db, user, study_id, body.version, body.reason)
    return _plan(db, study_id, user)


@router.post("/{study_id}/units/move")
def move_segments(study_id: int, body: UnitMove, user: User = Depends(survey_manager), db: Session = Depends(get_db)) -> dict:
    units.move(db, user, study_id, body.version, body.segment_ids, body.to_unit_id)
    return _plan(db, study_id, user)


@router.post("/{study_id}/units/{unit_id}/split")
def split_unit(study_id: int, unit_id: int, body: UnitSplit, user: User = Depends(survey_manager),
               db: Session = Depends(get_db)) -> dict:
    units.split(db, user, study_id, body.version, unit_id, body.segment_ids)
    return _plan(db, study_id, user)


@router.post("/{study_id}/units/merge")
def merge_units(study_id: int, body: UnitMerge, user: User = Depends(survey_manager), db: Session = Depends(get_db)) -> dict:
    units.merge(db, user, study_id, body.version, body.unit_ids)
    return _plan(db, study_id, user)


@router.post("/{study_id}/units/{unit_id}/assign")
def assign_unit(study_id: int, unit_id: int, body: UnitAssign, user: User = Depends(survey_manager),
                db: Session = Depends(get_db)) -> dict:
    units.assign(db, user, study_id, body.version, unit_id, body.assignee_id)
    return _plan(db, study_id, user)


@unit_router.get("/my/units")
def my_units(user: User = Depends(require_roles(Role.SURVEY_EXECUTIVE)), db: Session = Depends(get_db)) -> list[dict]:
    """The survey executive's units today. The property is just a label (PropertyLabel view)."""
    return [_unit_out(db, u, user) for u in units.mine(db, user)]


def _unit_out(db: Session, u, user: User) -> dict:
    study = db.get(Study, u.study_id)
    prog = units.progress(db, study.id).get(u.id, {"surveyed": 0, "gaps": 0})
    return unit_response(u, {**prog, "study_status": study.status, "lat": study.lat, "lon": study.lon,
                             "property": property_response(db.get(Property, study.property_id), user.role)})


@unit_router.get("/units/{unit_id}")
def get_unit(unit_id: int, user: User = Depends(require_roles(Role.SURVEY_MANAGER, Role.SURVEY_EXECUTIVE)),
             db: Session = Depends(get_db)) -> dict:
    """One unit: progress, the study's centre (for directions), the property as the role may see it."""
    return _unit_out(db, units.visible_unit(db, user, unit_id), user)


@unit_router.get("/units/{unit_id}/segments")
def unit_segments(unit_id: int, user: User = Depends(require_roles(Role.SURVEY_MANAGER, Role.SURVEY_EXECUTIVE)),
                  db: Session = Depends(get_db)) -> dict:
    return units.unit_geojson(db, units.visible_unit(db, user, unit_id))


# --- lane capture (survey executive) -----------------------------------------------------

@unit_router.post("/captures", status_code=201)
def submit_capture(body: CaptureIn, response: Response, user: User = Depends(require_roles(Role.SURVEY_EXECUTIVE)),
                   db: Session = Depends(get_db)) -> dict:
    """One lane. A retried submit with the same client_id returns the saved capture (200)."""
    c, created, warnings = captures.capture(db, user, body)
    db.commit()
    if not created:
        response.status_code = 200
    return {"id": c.id, "client_id": c.client_id, "segment_id": c.segment_id, "status": c.status,
            "time_band": c.time_band, "captured_at": c.captured_at, "gps_distance_m": c.gps_distance_m,
            "created": created, "warnings": warnings}


@unit_router.post("/units/{unit_id}/submit")
def submit_unit(unit_id: int, user: User = Depends(require_roles(Role.SURVEY_EXECUTIVE)),
                db: Session = Depends(get_db)) -> dict:
    u = captures.submit_unit(db, user, unit_id)
    db.commit()
    return _unit_out(db, u, user)
