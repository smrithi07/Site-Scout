"""Loads config/sitescout.yaml and registers each version in `config_versions`.

Rule 8: every snapshot records the config version it used. For that to mean anything, one
version string must always mean one content — so registering a version whose content differs
from what's already stored for that version is refused (bump `version` instead)."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import Connection, text

from app.core.settings import get_settings

REQUIRED_SECTIONS = ("version", "region", "grid", "localities", "osm", "ml_buildings", "mask", "jobs", "llm", "properties", "evaluation", "mock_rent_bands", "selection", "scoring", "studies")


class ConfigError(Exception):
    pass


@lru_cache
def load_config() -> dict:
    cfg = yaml.safe_load(Path(get_settings().sitescout_config).read_text())
    missing = [k for k in REQUIRED_SECTIONS if k not in cfg]
    if missing:
        raise ConfigError(f"config missing sections: {missing}")
    return cfg


def config_sha256(cfg: dict) -> str:
    # Hash the parsed content, not the file: comment/whitespace edits don't need a version bump.
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def register_config(conn: Connection) -> tuple[str, str]:
    """Idempotent. Returns (version, sha256); raises ConfigError on a same-version content change."""
    cfg = load_config()
    version, digest = str(cfg["version"]), config_sha256(cfg)
    conn.execute(text("""
        INSERT INTO config_versions (version, sha256, content) VALUES (:v, :h, CAST(:c AS jsonb))
        ON CONFLICT (version) DO NOTHING"""), dict(v=version, h=digest, c=json.dumps(cfg)))
    stored = conn.execute(text("SELECT sha256 FROM config_versions WHERE version = :v"), dict(v=version)).scalar()
    if stored != digest:
        raise ConfigError(f"config content changed but version is still {version!r} — bump `version` "
                          f"in config/sitescout.yaml (stored {stored[:12]}…, file {digest[:12]}…)")
    return version, digest
