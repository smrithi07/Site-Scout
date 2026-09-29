"""City-wide opportunity map (bonus). BD Manager only. "Start analysis" is the existing
POST /areas/reports with each pocket's `selection`."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.areas import _cells_geojson
from app.core.auth import Role, require_roles
from app.core.db import get_db
from app.models import User
from app.services import opportunities

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


@router.get("")
def opportunity_map(_: User = Depends(require_roles(Role.BD_MANAGER)), db: Session = Depends(get_db)) -> dict:
    result = opportunities.opportunity_map(db)
    for p in result["pockets"]:
        p["cells_geojson"] = _cells_geojson(p["cells"])
    return result
