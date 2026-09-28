"""M2 scouting: scout tasks and properties. Thin: access + masking decisions live in services and
`schemas/properties.py`; every response goes through the per-role builder."""
from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import BD_ROLES, Role, current_user, require_roles
from app.core.db import get_db
from app.core.errors import NotFound
from app.core.settings import get_settings
from app.models import PropertyNote, PropertyPhoto, User
from app.schemas.properties import DuplicateResolution, NoteIn, PropertyCreate, PropertyUpdate, property_response
from app.schemas.tasks import TaskCreate, TaskOut, TaskUpdate
from app.services import locate, properties, tasks

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


def _full(db: Session, p, user: User) -> dict:
    out = property_response(p, user.role)
    if user.role in BD_ROLES:
        out["notes"] = [{"id": n.id, "author_id": n.author_id, "kind": n.kind, "text": n.text, "created_at": n.created_at}
                        for n in db.scalars(select(PropertyNote).where(PropertyNote.property_id == p.id).order_by(PropertyNote.id))]
        out["photos"] = [{"id": ph.id, "filename": ph.filename, "content_type": ph.content_type, "bytes": ph.bytes,
                          "created_at": ph.created_at}
                         for ph in db.scalars(select(PropertyPhoto).where(PropertyPhoto.property_id == p.id).order_by(PropertyPhoto.id))]
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
    return [property_response(p, user.role) for p in properties.list_for(db, user, task_id, stage)]


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


@router.get("/properties/{property_id}/photos/{photo_id}")
def get_photo(property_id: int, photo_id: int, user: User = Depends(bd), db: Session = Depends(get_db)):
    properties.visible(db, user, property_id)
    photo = db.get(PropertyPhoto, photo_id)
    if photo is None or photo.property_id != property_id:
        raise NotFound("photo not found")
    return FileResponse(Path(get_settings().upload_dir) / photo.path, media_type=photo.content_type)
