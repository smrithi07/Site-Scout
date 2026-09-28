"""M3 catchment studies: request (BD Manager), inbox + planning (Survey Manager). Thin: rules live
in `services/studies.py`, masking in `schemas/` (the property goes through the per-role builder)."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import Role, require_roles
from app.core.db import get_db
from app.models import Property, StudySegment, User
from app.schemas.studies import CancelStudy, PlanDecision, StudyRequest, study_response
from app.services import properties, studies

router = APIRouter(prefix="/studies", tags=["studies"])
managers = require_roles(Role.BD_MANAGER, Role.SURVEY_MANAGER)


def _out(db: Session, study, user: User) -> dict:
    count, length = db.execute(select(func.count(), func.coalesce(func.sum(StudySegment.length_m), 0))
                               .where(StudySegment.study_id == study.id, StudySegment.to_survey)).one()
    return study_response(study, db.get(Property, study.property_id), user.role,
                          survey={"segments": count, "length_m": round(length)})


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
def list_studies(status: str | None = None, user: User = Depends(managers), db: Session = Depends(get_db)) -> list[dict]:
    return [_out(db, s, user) for s in studies.list_for(db, user, status)]


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
