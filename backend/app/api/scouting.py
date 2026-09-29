"""M2 scouting: scout tasks and properties. Thin: access + masking decisions live in services and
`schemas/properties.py`; every response goes through the per-role builder."""
from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import BD_ROLES, Role, current_user, require_roles
from app.core.db import get_db
from app.core.errors import NotFound
from app.core.settings import get_settings
from app.models import AuditEvent, FollowUp, Job, PropertyEvaluation, PropertyNote, PropertyPhoto, User
from app.schemas.properties import (
    DuplicateResolution,
    FollowUpIn,
    FollowUpResponse,
    NoteIn,
    PropertyCreate,
    PropertyUpdate,
    StageMove,
    property_response,
)
from app.schemas.tasks import TaskCreate, TaskOut, TaskUpdate
from app.services import evaluation, locate, pipeline, properties, tasks

router = APIRouter(tags=["scouting"])
bd = require_roles(*BD_ROLES)


# --- scout tasks -------------------------------------------------------------------------

@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(body: TaskCreate, user: User = Depends(require_roles(Role.BD_MANAGER)), db: Session = Depends(get_db)):
    task = tasks.create(db, user, body)
    db.commit()
    return task


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(user: User = Depends(bd), db: Session = Depends(get_db)):
    return tasks.list_for(db, user)


@router.get("/tasks/{task_id}")
def get_task(task_id: int, user: User = Depends(bd), db: Session = Depends(get_db)) -> dict:
    task = tasks.visible(db, user, task_id)
    return {**TaskOut.model_validate(task).model_dump(), **tasks.detail(db, task)}


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, body: TaskUpdate, user: User = Depends(bd), db: Session = Depends(get_db)):
    task = tasks.change(db, user, task_id, body.version, body.reason, body.status, body.assignee_id)
    db.commit()
    return task


# --- properties --------------------------------------------------------------------------

@router.get("/reference/locate", dependencies=[Depends(bd)])
def locate_point(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180),
                 db: Session = Depends(get_db)) -> dict:
    """Form prefill + live pin check: inside GCC? in water? ward, zone, pincode, nearby locality,
    and the illustrative rent band."""
    return locate.point_context(db, lat, lon)


def _latest_evaluation(db: Session, property_id: int) -> PropertyEvaluation | None:
    return db.scalar(select(PropertyEvaluation).where(PropertyEvaluation.property_id == property_id)
                     .order_by(PropertyEvaluation.version.desc()).limit(1))


def _full(db: Session, p, user: User) -> dict:
    out = property_response(p, user.role)
    if user.role in BD_ROLES:
        ev = _latest_evaluation(db, p.id)
        out["review"] = evaluation.review_card(p, ev)
        out["evaluation"] = _evaluation_out(ev) if ev else None
        job = db.get(Job, p.latest_job_id) if p.latest_job_id else None
        out["evaluation_job"] = {"id": job.id, "status": job.status, "error": job.error} if job else None
        out["follow_ups"] = [{"id": f.id, "kind": f.kind, "message": f.message, "status": f.status,
                              "response": f.response, "assignee_id": f.assignee_id, "created_at": f.created_at,
                              "responded_at": f.responded_at}
                             for f in db.scalars(select(FollowUp).where(FollowUp.property_id == p.id).order_by(FollowUp.id))]
        out["notes"] = [{"id": n.id, "author_id": n.author_id, "kind": n.kind, "text": n.text, "created_at": n.created_at}
                        for n in db.scalars(select(PropertyNote).where(PropertyNote.property_id == p.id).order_by(PropertyNote.id))]
        out["photos"] = [{"id": ph.id, "filename": ph.filename, "content_type": ph.content_type, "bytes": ph.bytes,
                          "created_at": ph.created_at}
                         for ph in db.scalars(select(PropertyPhoto).where(PropertyPhoto.property_id == p.id).order_by(PropertyPhoto.id))]
        creator = db.get(User, p.created_by)
        out["created_by_name"] = creator.name if creator else None
    if user.role == Role.BD_MANAGER:
        out["pipeline"] = pipeline.actions(db, p)
    return out


@router.post("/properties", status_code=201)
def create_property(body: PropertyCreate, response: Response, user: User = Depends(bd), db: Session = Depends(get_db)) -> dict:
    """Save first (Core rule 5). A retried submit with the same client_id returns the saved record (200)."""
    p, created = properties.create(db, user, body)
    db.commit()
    if not created:
        response.status_code = 200
    return _full(db, p, user)


@router.get("/properties")
def list_properties(task_id: int | None = None, stage: str | None = None, user: User = Depends(bd),
                    db: Session = Depends(get_db)) -> list[dict]:
    rows = properties.list_for(db, user, task_id, stage)
    newest = (select(PropertyEvaluation.property_id, func.max(PropertyEvaluation.version).label("v"))
              .where(PropertyEvaluation.property_id.in_([p.id for p in rows]))
              .group_by(PropertyEvaluation.property_id).subquery())
    latest = {e.property_id: e for e in db.scalars(select(PropertyEvaluation).join(
        newest, (PropertyEvaluation.property_id == newest.c.property_id) & (PropertyEvaluation.version == newest.c.v)))}
    # BD roles only (list_for returns nothing for others): latest outcome for list/board views.
    return [{**property_response(p, user.role), "outcome": getattr(latest.get(p.id), "outcome", None),
             "score": getattr(latest.get(p.id), "score", None)} for p in rows]


@router.get("/properties/{property_id}")
def get_property(property_id: int, user: User = Depends(bd), db: Session = Depends(get_db)) -> dict:
    return _full(db, properties.visible(db, user, property_id), user)


@router.patch("/properties/{property_id}")
def edit_property(property_id: int, body: PropertyUpdate, user: User = Depends(bd), db: Session = Depends(get_db)) -> dict:
    p = properties.update_fields(db, user, property_id, body.version, body.changes)
    db.commit()
    return _full(db, p, user)


@router.post("/properties/{property_id}/duplicate-resolution")
def resolve_duplicate(property_id: int, body: DuplicateResolution, user: User = Depends(bd),
                      db: Session = Depends(get_db)) -> dict:
    p = properties.resolve_duplicate(db, user, property_id, body.choice, body.target_id)
    db.commit()
    return _full(db, p, user)


@router.post("/properties/{property_id}/notes", status_code=201)
def add_note(property_id: int, body: NoteIn, user: User = Depends(bd), db: Session = Depends(get_db)) -> dict:
    note = properties.add_note(db, user, property_id, body.text)
    db.commit()
    return {"id": note.id, "kind": note.kind, "text": note.text}


@router.post("/properties/{property_id}/photos", status_code=201)
async def upload_photo(property_id: int, file: UploadFile = File(...), user: User = Depends(bd),
                       db: Session = Depends(get_db)) -> dict:
    data = await file.read()
    photo = properties.add_photo(db, user, property_id, file.filename or "photo", file.content_type or "", data)
    db.commit()
    return {"id": photo.id, "bytes": photo.bytes, "content_type": photo.content_type}


def _evaluation_out(ev: PropertyEvaluation) -> dict:
    out = {k: getattr(ev, k) for k in ("id", "version", "property_version", "trigger", "outcome", "score", "confidence",
                                       "hard_flags", "risks", "factors", "completeness", "snapshot_id",
                                       "config_version", "job_id", "created_at", "study_id", "summary_id", "diff",
                                       "narrative", "narrative_source")}
    meta = ev.narrative_meta or {}
    out["narrative_meta"] = {k: meta.get(k) for k in ("model", "cached", "attempts")} if meta else None
    return out


@router.get("/properties/{property_id}/evaluations")
def list_evaluations(property_id: int, user: User = Depends(bd), db: Session = Depends(get_db)) -> list[dict]:
    properties.visible(db, user, property_id)
    evs = db.scalars(select(PropertyEvaluation).where(PropertyEvaluation.property_id == property_id)
                     .order_by(PropertyEvaluation.version.desc()))
    return [{k: getattr(e, k) for k in ("id", "version", "trigger", "outcome", "score", "confidence", "created_at",
                                        "config_version", "study_id")} | {"has_diff": e.diff is not None} for e in evs]


@router.get("/properties/{property_id}/evaluations/{version}")
def get_evaluation(property_id: int, version: int, user: User = Depends(bd), db: Session = Depends(get_db)) -> dict:
    properties.visible(db, user, property_id)
    ev = db.scalar(select(PropertyEvaluation).where(PropertyEvaluation.property_id == property_id,
                                                    PropertyEvaluation.version == version))
    if ev is None:
        raise NotFound(f"evaluation v{version} of property {property_id} not found")
    return _evaluation_out(ev)


@router.post("/properties/{property_id}/evaluate", status_code=202)
def re_evaluate(property_id: int, user: User = Depends(require_roles(Role.BD_MANAGER)), db: Session = Depends(get_db)) -> dict:
    """Manual re-run (e.g. after a config change or a failed job)."""
    p = properties.visible(db, user, property_id)
    job_id = properties.request_evaluation(db, p, user, "manual")
    db.commit()
    return {"job_id": job_id}


@router.post("/properties/{property_id}/stage")
def move_stage(property_id: int, body: StageMove, user: User = Depends(require_roles(Role.BD_MANAGER)),
               db: Session = Depends(get_db)) -> dict:
    p = pipeline.move(db, user, property_id, body.to, body.reason, body.version)
    db.commit()
    return _full(db, p, user)


@router.post("/properties/{property_id}/follow-ups", status_code=201)
def request_follow_up(property_id: int, body: FollowUpIn, user: User = Depends(require_roles(Role.BD_MANAGER)),
                      db: Session = Depends(get_db)) -> dict:
    fu = pipeline.request_follow_up(db, user, property_id, body.kind, body.message, body.version)
    db.commit()
    return {"id": fu.id, "status": fu.status, "assignee_id": fu.assignee_id}


@router.get("/follow-ups")
def list_follow_ups(all: bool = False, user: User = Depends(bd), db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": f.id, "property_id": f.property_id, "kind": f.kind, "message": f.message, "status": f.status,
             "response": f.response, "created_at": f.created_at}
            for f in pipeline.follow_ups_for(db, user, only_open=not all)]


@router.post("/follow-ups/{follow_up_id}/respond")
def respond_follow_up(follow_up_id: int, body: FollowUpResponse, user: User = Depends(bd),
                      db: Session = Depends(get_db)) -> dict:
    fu = pipeline.respond(db, user, follow_up_id, body.response)
    db.commit()
    return {"id": fu.id, "status": fu.status, "property_id": fu.property_id}


@router.get("/properties/{property_id}/history")
def property_history(property_id: int, user: User = Depends(bd), db: Session = Depends(get_db)) -> list[dict]:
    """The property's audit trail: onboarding, edits, evaluations, stage moves with reasons."""
    properties.visible(db, user, property_id)
    rows = db.execute(select(AuditEvent, User.name).outerjoin(User, User.id == AuditEvent.actor_id)
                      .where(AuditEvent.entity_type == "property", AuditEvent.entity_id == str(property_id))
                      .order_by(AuditEvent.id))
    return [{**{k: getattr(e, k) for k in ("id", "at", "actor_id", "actor_role", "action", "from_state", "to_state",
                                           "reason", "details")}, "actor_name": name} for e, name in rows]


@router.get("/properties/{property_id}/photos/{photo_id}")
def get_photo(property_id: int, photo_id: int, user: User = Depends(bd), db: Session = Depends(get_db)):
    properties.visible(db, user, property_id)
    photo = db.get(PropertyPhoto, photo_id)
    if photo is None or photo.property_id != property_id:
        raise NotFound("photo not found")
    return FileResponse(Path(get_settings().upload_dir) / photo.path, media_type=photo.content_type)
