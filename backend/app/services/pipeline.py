"""The property pipeline (docs/DESIGN.md §6):

  Scouted → Under Review → Shortlisted → Study Requested → Study In Progress → Study Complete →
  { Approved | Rejected | On Hold }      (+ Needs follow-up, a loop back to Under Review)

- Only the BD Manager moves stages; every move needs a reason and the version the manager saw
  (optimistic lock: two managers moving the same property → the second gets 409).
- Study stages are entered by the study workflow (M3), not by a manual move.
- Reject → reopen is allowed (back to Under Review), with a reason.
- "Needs follow-up": the manager asks the executive for something (photos, a revisit, a rent
  check). The executive's response returns the property to Under Review — the executive causes that
  move by responding; they can't move stages themselves.
"""
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import Role
from app.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from app.core.locking import update_versioned
from app.models import FollowUp, Property, PropertyNote, User

STAGES = ["scouted", "under_review", "needs_follow_up", "shortlisted", "study_requested", "study_in_progress",
          "study_complete", "approved", "rejected", "on_hold"]
STUDY_STAGES = {"study_requested", "study_in_progress", "study_complete"}
MANAGER_MOVES = {
    "scouted": {"under_review", "rejected", "on_hold"},
    "under_review": {"shortlisted", "rejected", "on_hold"},
    "needs_follow_up": {"under_review", "rejected", "on_hold"},   # manager can withdraw the request
    "shortlisted": {"under_review", "rejected", "on_hold"},
    "study_requested": {"rejected", "on_hold"},
    "study_in_progress": {"rejected", "on_hold"},
    "study_complete": {"approved", "rejected", "on_hold"},
    "on_hold": {"under_review", "shortlisted", "rejected"},
    "rejected": {"under_review"},                                # reopen
    "approved": set(),
}
FOLLOW_UP_FROM = {"scouted", "under_review", "shortlisted", "on_hold"}
# Entered only by the study workflow (services/studies.py), never by a manual move.
STUDY_FLOW = {
    "shortlisted": {"study_requested"},
    "study_requested": {"study_in_progress", "shortlisted"},      # shortlisted = study cancelled
    "study_in_progress": {"study_complete", "shortlisted"},
}


def actions(db: Session, p: Property) -> dict:
    """What the manager can do next from here — the UI renders exactly this, so the stage rules
    live only in this module."""
    if p.status == "merged":
        return {"moves": [], "follow_up": {"allowed": False, "why": "merged into another property"}}
    creator = db.get(User, p.created_by)
    if p.stage not in FOLLOW_UP_FROM | {"needs_follow_up"}:
        follow_up = {"allowed": False, "why": f"not while {p.stage.replace('_', ' ')}"}
    elif creator is None or creator.role != Role.BD_EXECUTIVE:
        follow_up = {"allowed": False, "why": "added by a manager, no executive to ask"}
    else:
        follow_up = {"allowed": True, "assignee": creator.name}
    from app.core.config import load_config  # local: keeps this module config-free at import
    from_stages = load_config()["studies"]["request_from_stages"]
    study = ({"allowed": True} if p.stage in from_stages
             else {"allowed": False, "why": f"studies are requested from {', '.join(from_stages)}"})
    return {"moves": [s for s in STAGES if s in MANAGER_MOVES[p.stage]], "follow_up": follow_up, "study": study}


def study_transition(db: Session, actor: User, p: Property, to: str, *, reason: str, version: int,
                     details: dict | None = None) -> None:
    """Stage change caused by the study workflow (request, assignment, completion, cancellation)."""
    if to not in STUDY_FLOW.get(p.stage, set()):
        raise Conflict(f"Can't move from {p.stage} to {to} via the study workflow")
    old = p.stage
    update_versioned(db, Property, p.id, version, stage=to, updated_at=text("now()"))
    audit.record(db, actor=actor, entity_type="property", entity_id=p.id, action="stage_moved",
                 from_state=old, to_state=to, reason=reason, details={"via": "study", **(details or {})})
    db.flush()
    db.refresh(p)


def move(db: Session, actor: User, property_id: int, to: str, reason: str, version: int,
         details: dict | None = None) -> Property:
    if actor.role != Role.BD_MANAGER:
        raise Forbidden("Only the BD Manager moves pipeline stages")
    p = db.get(Property, property_id)
    if p is None:
        raise NotFound(f"property {property_id} not found")
    if p.status == "merged":
        raise Conflict("This entry was merged into another property; move that one instead")
    if to not in STAGES:
        raise Unprocessable(f"unknown stage {to!r}")
    if to in STUDY_STAGES:
        raise Conflict(f"'{to}' is set by the study workflow — use Request study")
    if to == "needs_follow_up":
        raise Conflict("Use a follow-up request to ask the executive for something")
    allowed = MANAGER_MOVES[p.stage]
    if to not in allowed:
        raise Conflict(f"Can't move from {p.stage} to {to}; allowed: {', '.join(sorted(allowed)) or 'none (final)'}")
    old = p.stage
    update_versioned(db, Property, p.id, version, stage=to, updated_at=text("now()"))
    if old == "needs_follow_up":  # manager withdrew the request
        db.execute(update(FollowUp).where(FollowUp.property_id == p.id, FollowUp.status == "open")
                   .values(status="withdrawn"))
    if old in STUDY_STAGES:  # rejected / on hold mid-study: cancel the study, keep its captured data
        from app.services import studies  # local: studies imports this module
        studies.cancel_open_for_property(db, actor, p.id, f"property moved to {to}: {reason}")
    audit.record(db, actor=actor, entity_type="property", entity_id=p.id, action="stage_moved",
                 from_state=old, to_state=to, reason=reason, details=details or {})
    db.flush()
    db.refresh(p)
    return p


def request_follow_up(db: Session, actor: User, property_id: int, kind: str, message: str, version: int) -> FollowUp:
    if actor.role != Role.BD_MANAGER:
        raise Forbidden("Only the BD Manager requests follow-ups")
    p = db.get(Property, property_id)
    if p is None:
        raise NotFound(f"property {property_id} not found")
    assignee = db.get(User, p.created_by)
    if assignee.role != Role.BD_EXECUTIVE:
        raise Unprocessable("Follow-ups go to the executive who onboarded the property; this one was added by a manager")
    if p.stage not in FOLLOW_UP_FROM | {"needs_follow_up"}:
        raise Conflict(f"Can't request a follow-up while the property is {p.stage}")
    old = p.stage
    if old != "needs_follow_up":
        update_versioned(db, Property, p.id, version, stage="needs_follow_up", updated_at=text("now()"))
    elif p.version != version:
        raise Conflict("The property changed since you loaded it; reload and retry")
    fu = FollowUp(property_id=p.id, requested_by=actor.id, assignee_id=assignee.id, kind=kind, message=message)
    db.add(fu)
    db.flush()
    audit.record(db, actor=actor, entity_type="property", entity_id=p.id, action="follow_up_requested",
                 from_state=old, to_state="needs_follow_up", reason=f"{kind}: {message}",
                 details={"follow_up_id": fu.id, "assignee_id": assignee.id})
    return fu


def respond(db: Session, actor: User, follow_up_id: int, response: str) -> FollowUp:
    fu = db.get(FollowUp, follow_up_id)
    if fu is None:
        raise NotFound(f"follow-up {follow_up_id} not found")
    if fu.assignee_id != actor.id:
        raise Forbidden("This follow-up isn't assigned to you")
    if fu.status != "open":
        raise Conflict(f"This follow-up is already {fu.status}")
    db.execute(update(FollowUp).where(FollowUp.id == fu.id)
               .values(status="responded", response=response, responded_at=text("now()")))
    db.add(PropertyNote(property_id=fu.property_id, author_id=actor.id, kind="follow_up",
                        text=f"Follow-up ({fu.kind}) response: {response}"))
    p = db.get(Property, fu.property_id)
    still_open = db.scalar(select(FollowUp.id).where(FollowUp.property_id == p.id, FollowUp.status == "open",
                                                     FollowUp.id != fu.id).limit(1))
    if p.stage == "needs_follow_up" and still_open is None:
        # The system returns the property to review because the executive responded (not a manual move).
        update_versioned(db, Property, p.id, p.version, stage="under_review", updated_at=text("now()"))
        audit.record(db, actor=actor, entity_type="property", entity_id=p.id, action="stage_moved",
                     from_state="needs_follow_up", to_state="under_review",
                     reason=f"follow-up #{fu.id} answered: {response[:200]}",
                     details={"system_transition": True, "follow_up_id": fu.id})
    else:
        audit.record(db, actor=actor, entity_type="property", entity_id=p.id, action="follow_up_answered",
                     reason=response[:200], details={"follow_up_id": fu.id})
    db.flush()
    db.refresh(fu)
    return fu


def follow_ups_for(db: Session, user: User, only_open: bool = True) -> list[FollowUp]:
    q = select(FollowUp).order_by(FollowUp.id.desc())
    if user.role == Role.BD_EXECUTIVE:
        q = q.where(FollowUp.assignee_id == user.id)
    elif user.role != Role.BD_MANAGER:
        return []
    if only_open:
        q = q.where(FollowUp.status == "open")
    return list(db.scalars(q))
