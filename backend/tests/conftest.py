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
    from app.llm import adapter
    monkeypatch.setattr(adapter, "configured_providers", lambda: ())
    monkeypatch.setattr(adapter, "guards", adapter._Guards())


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:  # runs lifespan → config registration, like production
        yield c


def bd_client() -> TestClient:
    """A client acting as the BD Manager — for tests about data, not access."""
    return TestClient(app, headers=headers(Role.BD_MANAGER))
