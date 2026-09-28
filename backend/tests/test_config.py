"""Phase 3a: one config version string always means one config content."""
import pytest
from sqlalchemy import text

from app.core import config as config_mod
from app.core.auth import Role
from app.core.config import ConfigError, config_sha256, load_config, register_config
from app.core.db import engine
from tests.conftest import headers


def test_hash_ignores_key_order_but_not_values():
    assert config_sha256({"a": 1, "b": 2}) == config_sha256({"b": 2, "a": 1})
    assert config_sha256({"a": 1}) != config_sha256({"a": 2})


def test_register_is_idempotent_for_unchanged_config():
    with engine.begin() as conn:
        assert register_config(conn) == register_config(conn)


def test_changed_content_under_same_version_is_refused(monkeypatch):
    changed = {**load_config(), "mask": {**load_config()["mask"], "min_blocking_share": 0.99}}
    monkeypatch.setattr(config_mod, "load_config", lambda: changed)
    with engine.connect() as conn:
        with pytest.raises(ConfigError, match="bump `version`"):
            register_config(conn)
        conn.rollback()


def test_new_version_registers(monkeypatch):
    bumped = {**load_config(), "version": "test-0.0.0"}
    monkeypatch.setattr(config_mod, "load_config", lambda: bumped)
    with engine.connect() as conn:
        assert register_config(conn)[0] == "test-0.0.0"
        conn.rollback()  # don't leave a test version behind
        assert conn.execute(text("SELECT count(*) FROM config_versions WHERE version = 'test-0.0.0'")).scalar() == 0


def test_config_endpoint_matches_registered_hash(client):
    body = client.get("/config", headers=headers(Role.SURVEY_EXECUTIVE)).json()
    with engine.connect() as conn:
        stored = conn.execute(text("SELECT sha256 FROM config_versions WHERE version = :v"),
                              dict(v=body["version"])).scalar()
    assert body["sha256"] == stored
