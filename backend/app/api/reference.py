"""Reference-data endpoints. Locality search feeds area selection and the property form (BD
roles); pincode shapes are also drawn on the Survey Manager's map."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth import BD_ROLES, Role, current_user, require_roles
from app.core.db import get_db
from app.schemas.reference import LocalitySearchResult, SnapshotOut
from app.services import localities, snapshots

router = APIRouter(tags=["reference"])


@router.get("/reference/snapshot", response_model=SnapshotOut, dependencies=[Depends(current_user)])
def active_snapshot(db: Session = Depends(get_db)):
    snap = snapshots.active_snapshot(db)
    return SnapshotOut.model_validate(
        {**{c: getattr(snap, c) for c in ("id", "status", "config_version", "created_at", "finished_at", "stats")},
         "sources": [s.__dict__ for s in snapshots.snapshot_sources(db, snap.id)]})


@router.get("/localities/search", response_model=LocalitySearchResult,
            dependencies=[Depends(require_roles(*BD_ROLES))])
def search_localities(q: str = Query(min_length=2, max_length=80), db: Session = Depends(get_db)):
    snapshot_id, candidates = localities.search(db, q)
    return {"query": q, "snapshot_id": snapshot_id, "candidates": candidates}


@router.get("/reference/pincodes/{pincode}",
            dependencies=[Depends(require_roles(*BD_ROLES, Role.SURVEY_MANAGER))])
def pincode_geometry(pincode: str, db: Session = Depends(get_db)) -> dict:
    return localities.pincode_feature(db, pincode)
