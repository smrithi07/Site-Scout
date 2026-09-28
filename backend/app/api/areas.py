"""M1 — Area Intelligence. BD Manager only for now; BD Executives get hotspots of their tasked
areas with scout tasks (Phase 6)."""
import h3
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.auth import Role, require_roles
from app.core.config import load_config
from app.core.db import get_db
from app.jobs import queue
from app.models import AreaReport, User
from app.services import area_report, selection, snapshots

router = APIRouter(prefix="/areas", tags=["areas"])
bd_manager = require_roles(Role.BD_MANAGER)


def _cells_geojson(cells: list[str]) -> dict:
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"h3": c},
         "geometry": {"type": "Polygon", "coordinates": [[[lng, lat] for lat, lng in
                                                           [*h3.cell_to_boundary(c), h3.cell_to_boundary(c)[0]]]]}}
        for c in cells]}


def _summary(r: AreaReport) -> dict:
    return {"id": r.id, "area_key": r.area_key, "version": r.version, "label": r.label, "status": r.status,
            "score": r.score, "rating": r.rating, "confidence": r.confidence, "created_at": r.created_at,
            "created_by": r.created_by, "snapshot_id": r.snapshot_id, "config_version": r.config_version,
            "narrative_source": r.narrative_source}


@router.get("/grid")
def selection_grid(_: User = Depends(bd_manager), db: Session = Depends(get_db)) -> dict:
    """Every selection cell (res 8) with the share of its score cells that are scoreable land, so
    the map can grey out water/airport/industrial cells before anyone clicks them."""
    snap = snapshots.active_snapshot(db)
    if snap.id not in _grid_cache:
        rows = db.execute(text("""
            SELECT c.parent_h3 AS h3, avg(f.scoreable::int) AS share
            FROM h3_cells c JOIN cell_features f USING (snapshot_id, h3)
            WHERE c.snapshot_id = :s AND c.res = :r GROUP BY c.parent_h3"""),
            dict(s=snap.id, r=load_config()["grid"]["score_res"])).all()
        share = {r.h3: round(float(r.share), 2) for r in rows}
        fc = _cells_geojson(sorted(share))
        for f in fc["features"]:
            f["properties"]["scoreable_share"] = share[f["properties"]["h3"]]
        _grid_cache.clear()
        _grid_cache[snap.id] = {"snapshot_id": snap.id, **fc}
    return _grid_cache[snap.id]


_grid_cache: dict[int, dict] = {}


@router.post("/preview")
def preview(sel: selection.Selection, _: User = Depends(bd_manager), db: Session = Depends(get_db)) -> dict:
    """Resolve a selection without running anything: the cells, the boundary used, warnings, and
    earlier reports of the exact same area — so the user can edit cells before running."""
    r = selection.resolve(db, sel)
    previous = db.scalars(select(AreaReport).where(AreaReport.area_key == r["area_key"])
                          .order_by(AreaReport.version.desc())).all()
    return {**{k: r[k] for k in ("label", "mode", "basis", "warnings", "non_contiguous", "area_km2", "area_key",
                                 "select_cells", "snapshot_id")},
            "score_cell_count": len(r["score_cells"]), "cells_geojson": _cells_geojson(r["select_cells"]),
            "previous_reports": [_summary(p) for p in previous]}


@router.post("/reports", status_code=202)
def run_report(sel: selection.Selection, user: User = Depends(bd_manager), db: Session = Depends(get_db)) -> dict:
    r = selection.resolve(db, sel)  # reject bad selections now (422), not minutes later in the job
    job = queue.enqueue(db, "area_report", {"selection": sel.model_dump(exclude_defaults=True), "actor_id": user.id},
                        user)
    db.commit()
    return {"job_id": job.id, "area_key": r["area_key"], "label": r["label"]}


@router.get("/reports")
def list_reports(area_key: str | None = None, limit: int = Query(50, le=200),
                 _: User = Depends(bd_manager), db: Session = Depends(get_db)) -> list[dict]:
    q = select(AreaReport).order_by(AreaReport.id.desc()).limit(limit)
    if area_key:
        q = q.where(AreaReport.area_key == area_key)
    return [_summary(r) for r in db.scalars(q)]


@router.get("/reports/{report_id}")
def get_report(report_id: int, _: User = Depends(bd_manager), db: Session = Depends(get_db)) -> dict:
    r = area_report.get_report(db, report_id)
    latest = db.scalar(select(func.max(AreaReport.version)).where(AreaReport.area_key == r.area_key))
    return {**_summary(r), "latest_version": latest, "selection": r.selection, "resolved": r.resolved,
            "result": r.result, "narrative": r.narrative, "select_cells": r.select_cells,
            "cells_geojson": _cells_geojson(r.select_cells)}


@router.get("/reports/{a_id}/compare/{b_id}")
def compare_reports(a_id: int, b_id: int, _: User = Depends(bd_manager), db: Session = Depends(get_db)) -> dict:
    return area_report.compare(area_report.get_report(db, a_id), area_report.get_report(db, b_id))
