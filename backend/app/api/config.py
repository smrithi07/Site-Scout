from fastapi import APIRouter, Depends

from app.core.auth import current_user
from app.core.config import config_sha256, load_config

router = APIRouter(tags=["config"], dependencies=[Depends(current_user)])


@router.get("/config")
def active_config() -> dict:
    """The weights/thresholds in force — the UI shows these next to every score."""
    cfg = load_config()
    return {"version": cfg["version"], "sha256": config_sha256(cfg), "content": cfg}
