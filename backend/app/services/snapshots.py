from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NoDataSnapshot
from app.models import DataSnapshot, DataSource


def active_snapshot(db: Session) -> DataSnapshot:
    """The latest `ready` snapshot — the only data analysis may read (Core rule 4)."""
    snap = db.scalar(select(DataSnapshot).where(DataSnapshot.status == "ready")
                     .order_by(DataSnapshot.id.desc()).limit(1))
    if snap is None:
        raise NoDataSnapshot()
    return snap


def snapshot_sources(db: Session, snapshot_id: int) -> list[DataSource]:
    return list(db.scalars(select(DataSource).where(DataSource.snapshot_id == snapshot_id)
                           .order_by(DataSource.key)))
