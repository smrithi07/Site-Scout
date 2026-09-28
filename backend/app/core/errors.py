from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.locking import StaleVersion


class NoDataSnapshot(Exception):
    """No `ready` data snapshot exists — the offline ingest hasn't been run."""


class NotFound(Exception):
    pass


class SelectionError(Exception):
    """An area selection that can't be analysed as given; the message says why and what to do."""


class Unprocessable(Exception):
    """Input that can't be saved as given (bad pin, invalid choice); the message says why. → 422"""


class Forbidden(Exception):
    """Row-level access denied (e.g. another executive's property). → 403"""


class Conflict(Exception):
    """The request is valid but the entity's current state doesn't allow it (e.g. retrying a job
    that isn't failed)."""


def register(app: FastAPI) -> None:
    @app.exception_handler(NoDataSnapshot)
    async def _no_snapshot(_: Request, exc: NoDataSnapshot) -> JSONResponse:
        return JSONResponse({"detail": "No ready data snapshot. Run `make ingest`."}, status_code=503)

    @app.exception_handler(NotFound)
    async def _not_found(_: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse({"detail": str(exc) or "Not found"}, status_code=404)

    @app.exception_handler(StaleVersion)
    async def _stale(_: Request, exc: StaleVersion) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(Conflict)
    async def _conflict(_: Request, exc: Conflict) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(SelectionError)
    async def _selection(_: Request, exc: SelectionError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(Unprocessable)
    async def _unprocessable(_: Request, exc: Unprocessable) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(Forbidden)
    async def _forbidden(_: Request, exc: Forbidden) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=403)
