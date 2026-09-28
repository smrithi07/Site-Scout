from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import load_config
from app.core.db import engine
from app.core.settings import get_settings

app = FastAPI(title="Savo SiteScout API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
        checks["config_version"] = load_config()["version"]
    except Exception as exc:
        checks["config_version"] = f"error: {exc.__class__.__name__}"

    ok = checks["db"] == "ok" and not str(checks["config_version"]).startswith("error")
    return JSONResponse({"status": "ok" if ok else "degraded", **checks}, status_code=200 if ok else 503)
