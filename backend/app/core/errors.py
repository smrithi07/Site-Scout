from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class NoDataSnapshot(Exception):
    """No `ready` data snapshot exists — the offline ingest hasn't been run."""


class NotFound(Exception):
    pass


def register(app: FastAPI) -> None:
    @app.exception_handler(NoDataSnapshot)
    async def _no_snapshot(_: Request, exc: NoDataSnapshot) -> JSONResponse:
        return JSONResponse({"detail": "No ready data snapshot. Run `make ingest`."}, status_code=503)

    @app.exception_handler(NotFound)
    async def _not_found(_: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse({"detail": str(exc) or "Not found"}, status_code=404)
