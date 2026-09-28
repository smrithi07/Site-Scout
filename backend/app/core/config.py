"""Loads config/sitescout.yaml. Full versioning/validation arrives in Phase 3."""
from functools import lru_cache
from pathlib import Path

import yaml

from app.core.settings import get_settings


@lru_cache
def load_config() -> dict:
    return yaml.safe_load(Path(get_settings().sitescout_config).read_text())
