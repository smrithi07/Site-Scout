"""Optimistic locking for mutable rows (Core rule 3): every mutable table has a `version` column,
and every update states the version it read. Two managers moving the same property at once →
the second gets a 409 and re-reads, instead of silently overwriting the first."""
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session


class StaleVersion(Exception):
    def __init__(self, entity: str, entity_id: Any, expected: int):
        super().__init__(f"{entity} {entity_id} was changed by someone else (expected version {expected}); reload and retry")


def update_versioned(db: Session, model: type, entity_id: Any, expected_version: int, **changes: Any) -> int:
    """UPDATE … WHERE id = :id AND version = :expected, bumping version. Returns the new version."""
    result = db.execute(
        update(model)
        .where(model.id == entity_id, model.version == expected_version)
        .values(**changes, version=model.version + 1)
        .returning(model.version))
    new_version = result.scalar()
    if new_version is None:
        raise StaleVersion(model.__tablename__, entity_id, expected_version)
    return new_version
