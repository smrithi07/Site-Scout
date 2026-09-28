"""Reference-data endpoints. Locality search feeds area selection and the property form (BD
roles); pincode shapes are also drawn on the Survey Manager's map."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
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


@router.get("/reference/service-area", dependencies=[Depends(current_user)])
def service_area(db: Session = Depends(get_db)) -> dict:
    """GCC outline for the map."""
    snap = snapshots.active_snapshot(db)
    row = db.execute(text("SELECT name, ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, 0.0002))::json AS g "
                          "FROM service_areas WHERE snapshot_id = :s"), dict(s=snap.id)).one()
    return {"type": "Feature", "properties": {"name": row.name, "snapshot_id": snap.id}, "geometry": row.g}


@router.get("/reference/stores", dependencies=[Depends(require_roles(*BD_ROLES))])
def savomart_stores(db: Session = Depends(get_db)) -> dict:
    """Operational Savomart stores near the service area (incl. just outside it), for the map."""
    snap = snapshots.active_snapshot(db)
    rows = db.execute(text("""
        SELECT s.store_code, s.name, s.zone, ST_X(s.geom) AS lon, ST_Y(s.geom) AS lat, s.fetched_at
        FROM stores s, service_areas sa
        WHERE s.snapshot_id = :s AND sa.snapshot_id = :s AND s.is_operational
          AND ST_DWithin(s.geom::geography, sa.geom::geography, 15000)
        ORDER BY s.store_code"""), dict(s=snap.id)).mappings().all()
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
         "properties": {"store_code": r["store_code"], "name": r["name"], "zone": r["zone"],
                        "fetched_at": r["fetched_at"].isoformat()}} for r in rows]}


@router.get("/reference/pincodes/{pincode}",
            dependencies=[Depends(require_roles(*BD_ROLES, Role.SURVEY_MANAGER))])
def pincode_geometry(pincode: str, db: Session = Depends(get_db)) -> dict:
    return localities.pincode_feature(db, pincode)
