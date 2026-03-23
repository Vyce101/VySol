"""FastAPI app entry point — CORS, router registration, startup."""

import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load .env before anything else
load_dotenv()

from core.config import parse_csv_env
from core.world_duplication import cleanup_incomplete_duplicate_worlds
from routers import worlds, ingestion, chat, graph, settings, entity_resolution

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="Sovereign World Sim", version="1.0.0")

default_cors_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
cors_origins = parse_csv_env(
    os.environ.get("CORS_ORIGINS"),
    default=default_cors_origins,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(worlds.router, prefix="/worlds", tags=["Worlds"])
app.include_router(ingestion.router, prefix="/worlds", tags=["Ingestion"])
app.include_router(chat.router, prefix="/worlds", tags=["Chat"])
app.include_router(graph.router, prefix="/worlds", tags=["Graph"])
app.include_router(entity_resolution.router, prefix="/worlds", tags=["Entity Resolution"])
app.include_router(settings.router, prefix="/settings", tags=["Settings"])


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.on_event("startup")
async def cleanup_incomplete_duplicate_worlds_on_startup():
    cleanup_incomplete_duplicate_worlds()
