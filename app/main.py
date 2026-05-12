from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.ingestion import cleanup_abandoned_attempt_workspaces
from app.logger import get_logger
from app.storage.database import bootstrap_global_database, close_global_connection

logger = get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        bootstrap_global_database()
        cleanup_abandoned_attempt_workspaces()
    except Exception:
        logger.critical("Unrecoverable startup database failure.", exc_info=True)
        raise

    try:
        yield
    finally:
        close_global_connection()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def read_health() -> dict[str, str]:
    return {"status": "ok"}
