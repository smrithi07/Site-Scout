from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import areas, auth, config, jobs, reference, scouting
from app.core import errors
from app.core.config import config_sha256, load_config, register_config
from app.core.db import engine
from app.core.settings import get_settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Refuse to start on a config whose content changed without a version bump (Core rule 8).
    with engine.begin() as conn:
        register_config(conn)
    yield


app = FastAPI(title="Savo SiteScout API", version="0.1.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=2048)  # map GeoJSON (grid ≈ 240 KB) compresses ~10×
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
errors.register(app)
app.include_router(auth.router)
app.include_router(config.router)
app.include_router(reference.router)
app.include_router(jobs.router)
app.include_router(areas.router)
app.include_router(scouting.router)


@app.get("/health")
def health() -> JSONResponse:
    checks: dict = {}
    try:
        with engine.connect() as conn:
            checks["db"] = "ok"
            checks["postgis"] = conn.execute(text("SELECT PostGIS_Lib_Version()")).scalar()
    except Exception as exc:  # report, don't crash — health must always answer
        checks["db"] = f"error: {exc.__class__.__name__}"
    try:
        cfg = load_config()
        checks["config_version"] = cfg["version"]
        checks["config_sha256"] = config_sha256(cfg)[:12]
    except Exception as exc:
        checks["config_version"] = f"error: {exc.__class__.__name__}"

    ok = checks["db"] == "ok" and not str(checks["config_version"]).startswith("error")
    return JSONResponse({"status": "ok" if ok else "degraded", **checks}, status_code=200 if ok else 503)
