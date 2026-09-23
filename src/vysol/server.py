"""Loopback application API and static frontend with durable world creation."""

from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import sqlite3
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from filelock import Timeout
from pydantic import BaseModel

from .books import ImportLimits
from .books.models import ImportFailure
from .books.import_logging import import_logger
from .creation import Creation
from .creation_api import creation_routes
from .creation_store import CreationConflict
from .credentials import FileCredentialVault
from .worlds import WorldStore


class Settings(BaseModel):
    background_speed: Literal["fast", "normal", "slow"]
    world_layout: Literal["shelf", "grid"] | None = None


def create_app(data_dir: Path | None = None, frontend_dir: Path | None = None,
               limits: ImportLimits | None = None, *, vault=None, embedder=None) -> FastAPI:
    root = (data_dir or Path(os.environ.get("VYSOL_DATA_DIR", "data"))).resolve()
    frontend = frontend_dir or Path(__file__).resolve().parents[2] / "frontend" / "dist" / "client"
    store = WorldStore(root)
    vault = vault or FileCredentialVault(root)
    creation = Creation(root, vault, embedder, limits)

    @asynccontextmanager
    async def lifespan(app):
        with import_logger(root) as logger:
            app.state.logger = logger
            creation.start_service(logger)
            logger.info("Application started")
            try:
                yield
            finally:
                creation.close()
                logger.info("Application stopped")

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.creation = creation

    @app.middleware("http")
    async def local_browser(request: Request, call_next):
        host = request.url.hostname
        origin = request.headers.get("origin")
        if host not in {"127.0.0.1", "localhost", "testserver"}:
            return JSONResponse({"detail": "Local access only."}, status_code=403)
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "This request must come from VySol."}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "This request must come from VySol."}, status_code=403)
        return await call_next(request)

    @app.exception_handler(OSError)
    @app.exception_handler(Timeout)
    @app.exception_handler(sqlite3.Error)
    @app.exception_handler(json.JSONDecodeError)
    async def storage_error(request, exc):
        app.state.logger.error("Application storage operation failed type=%s", type(exc).__name__)
        return JSONResponse({"detail": "Storage is unavailable. Please try again."}, status_code=503)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Default validation responses include inputs, which may contain secrets.
        return JSONResponse({"detail": "Check the required fields and their allowed values."}, status_code=422)

    @app.exception_handler(CreationConflict)
    async def conflict(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ImportFailure)
    async def invalid_book(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    def require_world(world_id: UUID):
        try:
            return store.get(str(world_id))
        except FileNotFoundError:
            raise HTTPException(404, "World not found.") from None

    app.include_router(creation_routes(creation))

    @app.get("/api/health")
    def health():
        return {"status": "ready", "app": "vysol"}

    @app.get("/api/worlds")
    def worlds():
        return store.list_worlds()

    @app.post("/api/worlds")
    @app.put("/api/worlds/{world_id}/imports/{operation_id}")
    def retired_creation():
        raise HTTPException(410, "Use the creation flow to submit and accept a complete world.")

    @app.get("/api/worlds/{world_id}/books")
    def books(world_id: UUID):
        require_world(world_id)
        return store.books(str(world_id))

    @app.get("/api/settings")
    def settings():
        return store.settings()

    @app.put("/api/settings")
    def update_settings(value: Settings):
        result = store.save_settings(value.background_speed, value.world_layout)
        app.state.logger.info("Appearance preferences saved")
        return result

    @app.get("/api/worlds/{world_id}/artwork")
    def artwork(world_id: UUID):
        world = require_world(world_id)
        if world["artwork"] == "custom":
            path = store.directory(str(world_id)) / "artwork.png"
            if path.resolve().is_relative_to(root) and path.is_file():
                return FileResponse(path)
        return FileResponse(frontend / "assets" / "frostwake.png")

    @app.get("/api/{unknown:path}")
    def missing_api(unknown: str):
        raise HTTPException(404, "Not found.")

    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app
