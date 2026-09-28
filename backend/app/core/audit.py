"""Audit writer (Core rule 3). Call it inside the same session/transaction as the state change,
so the event and the change commit or roll back together. The table itself is append-only."""
from typing import Any

from sqlalchemy import Connection
from sqlalchemy.orm import Session

from app.models import AuditEvent, User

SYSTEM = "system"


def record(db: Session | Connection, *, actor: User | None, entity_type: str, entity_id: Any,
           action: str, reason: str, from_state: str | None = None, to_state: str | None = None,
           details: dict | None = None) -> None:
    """`actor=None` means the system (worker, reaper). `reason` is required — the DB also checks."""
    if not reason or not reason.strip():
        raise ValueError("audit events need a reason")
    values = dict(actor_id=actor.id if actor else None, actor_role=actor.role if actor else SYSTEM,
                  entity_type=entity_type, entity_id=str(entity_id), action=action,
                  from_state=from_state, to_state=to_state, reason=reason.strip(), details=details or {})
    if isinstance(db, Session):
        db.add(AuditEvent(**values))
    else:
        db.execute(AuditEvent.__table__.insert().values(**values))
