"""Scout tasks (docs/DESIGN.md §6): a BD Manager turns report hotspots / cells into a task for a
BD Executive. Executives see their own tasks and only the hotspots inside them (docs/DESIGN.md §4)."""
import h3
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import Role
from app.core.config import load_config
from app.core.errors import Forbidden, NotFound, Unprocessable
from app.core.locking import update_versioned
from app.models import AreaReport, Property, ScoutTask, User
from app.schemas.tasks import TaskCreate

# Who may move a task where. Executives report progress; managers can also cancel/reopen.
EXECUTIVE_MOVES = {("open", "in_progress"), ("in_progress", "done"), ("open", "done")}


def create(db: Session, actor: User, data: TaskCreate) -> ScoutTask:
    assignee = db.get(User, data.assignee_id)
    if assignee is None or assignee.role != Role.BD_EXECUTIVE:
        raise Unprocessable("Scout tasks can only be assigned to a BD Executive")
    select_res = load_config()["grid"]["select_res"]
    hotspots = list(dict.fromkeys(data.hotspot_cells))
    if data.source_report_id:
        report = db.get(AreaReport, data.source_report_id)
        if report is None:
            raise NotFound(f"area report {data.source_report_id} not found")
        known = {h["h3"] for h in report.result["hotspots"]}
        if set(hotspots) - known:
            raise Unprocessable("hotspot_cells must be hotspots of the source report")
    elif hotspots:
        raise Unprocessable("hotspot_cells need a source_report_id")
    cells = sorted(set(data.target_cells) | {h3.cell_to_parent(c, select_res) for c in hotspots})
    if not cells:
        raise Unprocessable("A task needs target cells or hotspots")
    unknown = set(cells) - set(db.scalars(text("SELECT h3 FROM h3_cells WHERE res = :r AND h3 = ANY(:c) AND snapshot_id = "
                                               "(SELECT max(id) FROM data_snapshots WHERE status = 'ready')"),
                                          dict(r=select_res, c=cells)))
    if unknown:
        raise Unprocessable(f"{len(unknown)} target cell(s) are not selection cells in the service area")
    task = ScoutTask(title=data.title, note=data.note, assignee_id=assignee.id, created_by=actor.id,
                     due_date=data.due_date, source_report_id=data.source_report_id, target_cells=cells,
                     hotspot_cells=hotspots)
    db.add(task)
    db.flush()
    audit.record(db, actor=actor, entity_type="scout_task", entity_id=task.id, action="created", to_state="open",
                 reason=f"assigned to {assignee.name}", details={"cells": len(cells), "hotspots": len(hotspots),
                                                                 "source_report_id": data.source_report_id})
    return task


def visible(db: Session, user: User, task_id: int) -> ScoutTask:
    task = db.get(ScoutTask, task_id)
    if task is None:
        raise NotFound(f"scout task {task_id} not found")
    if user.role == Role.BD_MANAGER or (user.role == Role.BD_EXECUTIVE and task.assignee_id == user.id):
        return task
    raise Forbidden("This scout task isn't assigned to you")


def list_for(db: Session, user: User) -> list[ScoutTask]:
    q = select(ScoutTask).order_by(ScoutTask.id.desc())
    if user.role == Role.BD_EXECUTIVE:
        q = q.where(ScoutTask.assignee_id == user.id)
    return list(db.scalars(q))


def detail(db: Session, task: ScoutTask) -> dict:
    """The task plus what an executive needs on the map: the hotspots inside it (with their 'why')
    and the properties already scouted for it."""
    hotspots = []
    if task.source_report_id:
        report = db.get(AreaReport, task.source_report_id)
        wanted = set(task.hotspot_cells) or None
        hotspots = [h for h in report.result["hotspots"]
                    if (h["h3"] in wanted if wanted else h3.cell_to_parent(h["h3"], load_config()["grid"]["select_res"])
                        in task.target_cells)]
    props = db.scalars(select(Property).where(Property.task_id == task.id, Property.status != "merged")).all()
    return {"hotspots": hotspots,
            "properties": [{"id": p.id, "label": p.label, "lat": p.lat, "lon": p.lon, "stage": p.stage,
                            "status": p.status} for p in props]}


def change(db: Session, actor: User, task_id: int, version: int, reason: str,
           status: str | None = None, assignee_id: int | None = None) -> ScoutTask:
    task = visible(db, actor, task_id)
    changes = {}
    if status and status != task.status:
        if actor.role == Role.BD_EXECUTIVE and (task.status, status) not in EXECUTIVE_MOVES:
            raise Forbidden(f"Executives can't move a task from {task.status} to {status}")
        changes["status"] = status
    if assignee_id and assignee_id != task.assignee_id:
        if actor.role != Role.BD_MANAGER:
            raise Forbidden("Only the BD Manager can reassign a task")
        new = db.get(User, assignee_id)
        if new is None or new.role != Role.BD_EXECUTIVE:
            raise Unprocessable("Scout tasks can only be assigned to a BD Executive")
        changes["assignee_id"] = assignee_id
    if not changes:
        return task
    old_status, old_assignee = task.status, task.assignee_id
    update_versioned(db, ScoutTask, task.id, version, **changes, updated_at=text("now()"))
    audit.record(db, actor=actor, entity_type="scout_task", entity_id=task.id,
                 action="reassigned" if "assignee_id" in changes and "status" not in changes else "status_changed",
                 from_state=old_status, to_state=changes.get("status", old_status), reason=reason,
                 details={"assignee": [old_assignee, changes.get("assignee_id", old_assignee)]})
    db.flush()
    db.refresh(task)
    return task
