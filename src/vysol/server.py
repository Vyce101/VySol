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
from .chronicles import ChronicleService
from .chronicles_api import chronicle_routes
from .credentials import FileCredentialVault
from .worlds import WorldStore, latest_timestamp


class Settings(BaseModel):
    background_speed: Literal["fast", "normal", "slow"]
    world_layout: Literal["shelf", "grid"] | None = None
    chat_appearance: Literal["focused", "full_overlay"] | None = None


def create_app(data_dir: Path | None = None, frontend_dir: Path | None = None,
               limits: ImportLimits | None = None, *, vault=None, embedder=None, chat_client=None) -> FastAPI:
    root = (data_dir or Path(os.environ.get("VYSOL_DATA_DIR", "data"))).resolve()
    frontend = frontend_dir or Path(__file__).resolve().parents[2] / "frontend" / "dist" / "client"
    store = WorldStore(root)
    vault = vault or FileCredentialVault(root)
    creation = Creation(root, vault, embedder, limits)
    chronicles = ChronicleService(creation, chat_client=chat_client)

    @asynccontextmanager
    async def lifespan(app):
        with import_logger(root) as logger:
            app.state.logger = logger
            creation.start_service(logger)
            chronicles.start_service(logger)
            logger.info("Application started")
            try:
                yield
            finally:
                chronicles.close()
                creation.close()
                logger.info("Application stopped")

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.creation = creation
    app.state.chronicles = chronicles

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
    app.include_router(chronicle_routes(chronicles))

    @app.get("/api/health")
    def health():
        return {"status": "ready", "app": "vysol"}

    @app.get("/api/worlds")
    def worlds():
        return store.list_worlds(chronicles.world_activity())

    @app.get("/api/worlds/{world_id}")
    def world_detail(world_id: UUID):
        identity = str(world_id)
        try:
            world = store.get(identity)
        except FileNotFoundError:
            world = None
        attempt = creation.store.get(identity)
        if world is None and attempt is None:
            raise HTTPException(404, "World not found.")

        chronicle_activity = chronicles.world_activity().get(identity)

        attempt_public = creation.store.public(attempt) if attempt else None
        attempt_books = {book["id"]: book for book in (attempt_public or {}).get("books", [])}
        if world is not None:
            books = []
            for book in store.books(identity):
                creation_book = attempt_books.get(book["id"])
                books.append({
                    "id": book["id"],
                    "filename": book["filename"],
                    "position": book["position"],
                    "state": creation_book["state"] if creation_book else "done",
                    "chunks_done": creation_book["chunks_done"] if creation_book else None,
                    "chunks_total": creation_book["chunks_total"] if creation_book else None,
                })
        else:
            books = [{
                "id": book["id"],
                "filename": book["filename"],
                "position": book.get("position"),
                "state": book.get("state", "waiting"),
                "chunks_done": book.get("chunks_done", 0),
                "chunks_total": book.get("chunks_total", 0),
            } for book in attempt_public["books"]]

        config = (world or {}).get("processing") or (attempt or {}).get("config") or {}
        completed_books = sum(book["state"] == "done" for book in books)
        chunks_done = attempt_public.get("chunks_done") if attempt_public else None
        chunks_total = attempt_public.get("chunks_total") if attempt_public else None
        state = attempt["state"] if attempt else "complete"
        return {
            "id": identity,
            "name": (world or attempt)["name"],
            "created_at": (world or attempt).get("created_at"),
            "last_used_at": latest_timestamp((world or {}).get("last_used_at"), chronicle_activity)
            if world is not None else attempt.get("updated_at"),
            "artwork": (world or {}).get("artwork", "frostwake"),
            "sources_locked": bool((world or {}).get("sources_locked", attempt is not None)),
            "state": state,
            "book_count": len(books),
            "books": books,
            "progress": {
                "chunks_done": chunks_done,
                "chunks_total": chunks_total,
                "books_done": attempt_public.get("books_done", completed_books) if attempt_public else completed_books,
                "books_total": len(books),
            },
            "processing": {
                "model": config.get("model"),
                "max_chunk_size": config.get("size"),
                "boundary_search_distance": config.get("search"),
            },
        }

    @app.post("/api/worlds/{world_id}/activity")
    def record_world_activity(world_id: UUID):
        require_world(world_id)
        return store.record_activity(str(world_id))

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
        result = store.save_settings(value.background_speed, value.world_layout, value.chat_appearance)
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
