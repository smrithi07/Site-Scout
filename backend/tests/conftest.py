import pytest
from fastapi.testclient import TestClient

from app.core.auth import Role, token_for
from app.main import app

# Seeded demo users (migration 0004).
USER_IDS = {Role.BD_MANAGER: 1, Role.BD_EXECUTIVE: 2, Role.SURVEY_MANAGER: 3, Role.SURVEY_EXECUTIVE: 4}


def headers(role: Role) -> dict:
    return {"Authorization": f"Bearer {token_for(USER_IDS[role])}"}


@pytest.fixture(autouse=True)
def no_real_llm_calls(monkeypatch):
    """The suite must never spend API quota: jobs run template-only unless a test passes its own
    fake providers to `adapter.narrate`. Fresh circuit-breaker state per test."""
    from app.jobs import queue
    from app.llm import adapter
    monkeypatch.setattr(adapter, "configured_providers", lambda: ())
    monkeypatch.setattr(adapter, "guards", adapter._Guards())
    # Jobs enqueued by services (e.g. property evaluations) go to the test queue, never the live worker's.
    monkeypatch.setattr(queue, "DEFAULT_QUEUE", "test")


def purge_scouting_test_data() -> None:
    """Remove everything scouting tests create (labels/titles start with 'TEST '), including
    immutable rows via the explicit purge switch and uploaded photo files."""
    import shutil
    from pathlib import Path

    from sqlalchemy import text

    from app.core.db import engine
    from app.core.settings import get_settings

    with engine.begin() as conn:
        ids = conn.execute(text("SELECT id FROM properties WHERE label LIKE 'TEST %'")).scalars().all()
        conn.execute(text("SET LOCAL sitescout.purge = 'on'"))
        # studies of test properties, and test captures (notes start with 'TEST')
        sids = conn.execute(text("SELECT id FROM studies WHERE property_id = ANY(:i)"), dict(i=ids)).scalars().all()
        conn.execute(text("DELETE FROM study_segments WHERE study_id = ANY(:s)"), dict(s=sids))
        conn.execute(text("DELETE FROM survey_units WHERE study_id = ANY(:s)"), dict(s=sids))
        conn.execute(text("DELETE FROM catchment_summaries WHERE study_id = ANY(:s)"), dict(s=sids))
        conn.execute(text("DELETE FROM segment_captures WHERE study_id = ANY(:s) OR notes LIKE 'TEST%'"), dict(s=sids))
        conn.execute(text("DELETE FROM studies WHERE id = ANY(:s)"), dict(s=sids))
        for table in ("property_notes", "property_photos", "property_evaluations", "follow_ups"):
            conn.execute(text(f"DELETE FROM {table} WHERE property_id = ANY(:i)"), dict(i=ids))
        conn.execute(text("UPDATE properties SET duplicate_of = NULL WHERE id = ANY(:i)"), dict(i=ids))
        conn.execute(text("DELETE FROM properties WHERE id = ANY(:i)"), dict(i=ids))
        conn.execute(text("DELETE FROM scout_tasks WHERE title LIKE 'TEST %'"))
        conn.execute(text("DELETE FROM area_reports WHERE job_id IN (SELECT id FROM jobs WHERE queue = 'test')"))
        conn.execute(text("DELETE FROM jobs WHERE queue = 'test'"))
    for i in ids:
        shutil.rmtree(Path(get_settings().upload_dir) / "properties" / str(i), ignore_errors=True)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:  # runs lifespan → config registration, like production
        yield c


def bd_client() -> TestClient:
    """A client acting as the BD Manager — for tests about data, not access."""
    return TestClient(app, headers=headers(Role.BD_MANAGER))
