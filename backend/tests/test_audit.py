"""Phase 3b: the audit log is append-only at the database level and always has a reason."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core import audit
from app.core.auth import Role
from app.core.db import SessionLocal, engine
from app.models import User
from tests.conftest import USER_IDS, headers


def _write_one(reason: str = "test event") -> int:
    with SessionLocal() as db:
        audit.record(db, actor=db.get(User, USER_IDS[Role.BD_MANAGER]), entity_type="test", entity_id="x",
                     action="poked", reason=reason, from_state="a", to_state="b")
        db.commit()
    with engine.connect() as conn:
        return conn.execute(text("SELECT max(id) FROM audit_events")).scalar()


@pytest.mark.parametrize("sql", ["UPDATE audit_events SET reason = 'rewritten' WHERE id = :id",
                                 "DELETE FROM audit_events WHERE id = :id",
                                 "TRUNCATE audit_events"])
def test_history_cannot_be_rewritten_or_erased(sql):
    event_id = _write_one()
    with engine.connect() as conn, pytest.raises(DBAPIError, match="append-only"):
        conn.execute(text(sql), dict(id=event_id))
    with engine.connect() as conn:
        assert conn.execute(text("SELECT reason FROM audit_events WHERE id = :id"), dict(id=event_id)).scalar() == "test event"


def test_reason_is_required_by_writer_and_database():
    with pytest.raises(ValueError):
        _write_one(reason="   ")
    with engine.connect() as conn, pytest.raises(IntegrityError, match="ck_audit_reason_required"):
        conn.execute(text("INSERT INTO audit_events (actor_role, entity_type, entity_id, action, reason) "
                          "VALUES ('system', 'test', 'x', 'poked', ' ')"))


def test_event_rolls_back_with_its_change():
    # Same transaction as the change: if the change is abandoned, so is the event.
    with engine.connect() as conn:
        before = conn.execute(text("SELECT count(*) FROM audit_events")).scalar()
    with SessionLocal() as db:
        audit.record(db, actor=None, entity_type="test", entity_id="y", action="poked", reason="then rolled back")
        db.flush()
        db.rollback()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM audit_events")).scalar() == before


def test_audit_endpoint_is_managers_only(client):
    _write_one()
    params = {"entity_type": "test", "entity_id": "x"}
    rows = client.get("/audit", params=params, headers=headers(Role.BD_MANAGER)).json()
    assert rows[-1]["actor_role"] == "bd_manager" and rows[-1]["reason"] == "test event"
    assert client.get("/audit", params=params, headers=headers(Role.SURVEY_EXECUTIVE)).status_code == 403
