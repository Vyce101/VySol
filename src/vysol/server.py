"""Loopback application API and static frontend; uploads stream before conversion."""

from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
from typing import Literal
from urllib.parse import unquote
from uuid import UUID

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from filelock import FileLock, Timeout
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

from .books import import_books, Upload, ImportLimits
from .books.import_logging import import_logger
from .worlds import WorldStore, atomic_json


class NewWorld(BaseModel):
    id: UUID
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        if not value.strip():
            raise ValueError("Give your world a name.")
        return value.strip()


class Settings(BaseModel):
    background_speed: Literal["fast", "normal", "slow"]
    world_layout: Literal["shelf", "grid"] | None = None


def create_app(data_dir: Path | None = None, frontend_dir: Path | None = None,
               limits: ImportLimits | None = None) -> FastAPI:
    root = (data_dir or Path(os.environ.get("VYSOL_DATA_DIR", "data"))).resolve()
    frontend = frontend_dir or Path(__file__).resolve().parents[2] / "frontend" / "dist" / "client"
    store = WorldStore(root)
    limits = limits or ImportLimits()

    @asynccontextmanager
    async def lifespan(app):
        with import_logger(root) as logger:
            app.state.logger = logger
            logger.info("Application started")
            yield
            logger.info("Application stopped")

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)

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
    @app.exception_handler(json.JSONDecodeError)
    async def storage_error(request, exc):
        app.state.logger.error("Application storage operation failed type=%s", type(exc).__name__)
        return JSONResponse({"detail": "Storage is unavailable. Please try again."}, status_code=503)

    def require_world(world_id: UUID):
        try:
            return store.get(str(world_id))
        except FileNotFoundError:
            raise HTTPException(404, "World not found.") from None

    @app.get("/api/health")
    def health():
        return {"status": "ready", "app": "vysol"}

    @app.get("/api/worlds")
    def worlds():
        return store.list_worlds()

    @app.post("/api/worlds")
    def create(world: NewWorld):
        result = store.create(str(world.id), world.name)
        app.state.logger.info("World available world_id=%s", world.id)
        return result

    @app.get("/api/worlds/{world_id}/books")
    def books(world_id: UUID):
        require_world(world_id)
        return store.books(str(world_id))

    # Client-generated operation IDs allow exact reconciliation after a lost response.
    def operation_path(world_id: UUID, operation_id: UUID):
        folder = store.directory(str(world_id)) / "imports"
        folder.mkdir(exist_ok=True)
        return folder / f"{operation_id}.json"

    @app.get("/api/worlds/{world_id}/imports/{operation_id}")
    def import_status(world_id: UUID, operation_id: UUID):
        require_world(world_id)
        path = operation_path(world_id, operation_id)
        if not path.exists():
            return {"status": "unknown"}
        result = json.loads(path.read_text(encoding="utf-8"))
        if result["status"] == "pending":
            # Recover a committed import whose result record was interrupted.
            for book in store.books(str(world_id)):
                if (book["comparison_name"] == result["comparison_name"]
                        and store.original_digest(str(world_id), book) == result.get("content_digest")):
                    return {"status": "done", "filename": result["filename"], "book_id": book["id"], "error": None}
            lock = FileLock(str(path) + ".lock", timeout=0)
            try:
                with lock:
                    return {"status": "unknown"}
            except Timeout:
                pass
        return result

    def convert(world_id: UUID, operation_id: UUID, filename: str, content: bytes):
        from .books.storage import validate_upload
        from .books.models import ImportFailure
        path = operation_path(world_id, operation_id)
        with (FileLock(root / "locks" / f"api-import-{world_id}.lock", timeout=30),
              FileLock(str(path) + ".lock", timeout=30)):
            if path.exists():
                prior = import_status(world_id, operation_id)
                if prior["status"] == "done":
                    return prior
            try:
                comparison, _ = validate_upload(Upload(filename, content))
            except ImportFailure:
                comparison = ""
            existing = any(b["comparison_name"] == comparison for b in store.books(str(world_id)))
            if not existing:
                atomic_json(path, {"status": "pending", "filename": filename, "comparison_name": comparison,
                                   "content_digest": hashlib.sha256(content).hexdigest()})
            outcome = import_books(str(world_id), [Upload(filename, content)], data_dir=root, limits=limits)[0]
            result = {"status": "done", "filename": filename, "book_id": outcome.book.book_id if outcome.book else None,
                      "error": outcome.error, "message": outcome.message}
            atomic_json(path, result)
            return result

    @app.put("/api/worlds/{world_id}/imports/{operation_id}")
    async def upload(world_id: UUID, operation_id: UUID, request: Request):
        require_world(world_id)
        filename = unquote(request.headers.get("x-filename", ""))
        chunks = bytearray()
        async for chunk in request.stream():
            if len(chunks) + len(chunk) > limits.max_upload_bytes:
                return JSONResponse({"status": "done", "error": "size_limit", "message": "This book exceeds the 100 MiB upload limit."}, status_code=413)
            chunks.extend(chunk)
        return await run_in_threadpool(convert, world_id, operation_id, filename, bytes(chunks))

    @app.get("/api/settings")
    def settings():
        return store.settings()

    @app.put("/api/settings")
    def update_settings(value: Settings):
        result = store.save_settings(value.background_speed, value.world_layout)
        app.state.logger.info("Background transition preference saved speed=%s", value.background_speed)
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
