from pathlib import Path
from typing import NoReturn
from uuid import UUID

from app.logger import get_logger
from app.storage.paths import get_worlds_directory

logger = get_logger()
SOURCES_DIRECTORY_NAME = "sources"


class WorldFolderValidationError(ValueError):
    pass


def create_committed_world_folder(world_id: str) -> Path:
    world_directory = resolve_world_directory(world_id)
    sources_directory = resolve_world_sources_directory(world_id)

    try:
        world_directory.mkdir(parents=True, exist_ok=True)
        sources_directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.error("Failed to create committed world folder.", exc_info=True)
        logger.debug("Failed committed world folder ID: %s", normalize_world_id(world_id))
        raise

    logger.info("Created committed world folder: %s", normalize_world_id(world_id))
    return world_directory


def resolve_world_directory(world_id: str) -> Path:
    return get_worlds_directory() / normalize_world_id(world_id)


def resolve_world_sources_directory(world_id: str) -> Path:
    return resolve_world_directory(world_id) / SOURCES_DIRECTORY_NAME


def normalize_world_id(world_id: str) -> str:
    if not isinstance(world_id, str):
        reject_invalid_world_id()

    try:
        return str(UUID(world_id))
    except ValueError:
        reject_invalid_world_id()


def reject_invalid_world_id() -> NoReturn:
    logger.warning("Invalid committed world folder ID.")
    raise WorldFolderValidationError("Committed world folder ID must be a UUID.")
