import sqlite3
from pathlib import Path

from app.logger import get_logger
from app.storage.world_folders import (
    create_committed_world_folder,
    normalize_world_id,
    resolve_world_directory,
)
from app.storage.world_migrations import (
    apply_world_migrations,
    get_world_schema_version,
)

logger = get_logger()
WORLD_DATABASE_FILE_NAME = "world.sqlite"
CORRUPTED_DATABASE_ERROR_MESSAGES = (
    "database disk image is malformed",
    "file is not a database",
)


class MissingWorldDatabaseError(FileNotFoundError):
    pass


def resolve_world_database_path(world_id: str) -> Path:
    return resolve_world_directory(world_id) / WORLD_DATABASE_FILE_NAME


def bootstrap_world_database(world_id: str) -> sqlite3.Connection:
    normalized_world_id = normalize_world_id(world_id)
    connection: sqlite3.Connection | None = None

    try:
        world_directory = create_committed_world_folder(normalized_world_id)
        database_path = world_directory / WORLD_DATABASE_FILE_NAME
        was_created = not database_path.exists()
        connection = connect_to_world_database(database_path)
        current_version = get_world_schema_version(connection)
        logger.debug("World database ID: %s", normalized_world_id)
        logger.debug("Current world database schema version: %s", current_version)
        apply_world_migrations(connection)
    except sqlite3.DatabaseError as error:
        close_connection_if_needed(connection)
        if is_corrupted_world_database_error(error):
            logger.critical("Unrecoverable corrupted world database open.", exc_info=True)
            logger.debug("Corrupted world database ID: %s", normalized_world_id)
            raise

        logger.error("Failed to open or migrate world database.", exc_info=True)
        logger.debug("Failed world database ID: %s", normalized_world_id)
        raise
    except (OSError, sqlite3.Error):
        close_connection_if_needed(connection)
        logger.error("Failed to open or migrate world database.", exc_info=True)
        logger.debug("Failed world database ID: %s", normalized_world_id)
        raise

    if was_created:
        logger.info("Created world database.")
    else:
        logger.info("Opened world database.")

    logger.debug("Opened world database ID: %s", normalized_world_id)
    return connection


def open_world_database(world_id: str) -> sqlite3.Connection:
    return bootstrap_world_database(world_id)


def open_existing_world_database(world_id: str) -> sqlite3.Connection:
    normalized_world_id = normalize_world_id(world_id)
    database_path = resolve_world_database_path(normalized_world_id)
    if not database_path.is_file():
        logger.error("Missing world database.")
        logger.debug("Missing world database ID: %s", normalized_world_id)
        raise MissingWorldDatabaseError("World database does not exist.")

    connection: sqlite3.Connection | None = None
    try:
        connection = connect_to_world_database(database_path)
        current_version = get_world_schema_version(connection)
        logger.debug("World database ID: %s", normalized_world_id)
        logger.debug("Current world database schema version: %s", current_version)
        apply_world_migrations(connection)
    except sqlite3.DatabaseError as error:
        close_connection_if_needed(connection)
        if is_corrupted_world_database_error(error):
            logger.critical("Unrecoverable corrupted world database open.", exc_info=True)
            logger.debug("Corrupted world database ID: %s", normalized_world_id)
            raise

        logger.error("Failed to open or migrate existing world database.", exc_info=True)
        logger.debug("Failed world database ID: %s", normalized_world_id)
        raise
    except (OSError, sqlite3.Error):
        close_connection_if_needed(connection)
        logger.error("Failed to open or migrate existing world database.", exc_info=True)
        logger.debug("Failed world database ID: %s", normalized_world_id)
        raise

    logger.info("Opened existing world database.")
    logger.debug("Opened existing world database ID: %s", normalized_world_id)
    return connection


def connect_to_world_database(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


def is_corrupted_world_database_error(error: sqlite3.DatabaseError) -> bool:
    message = str(error).casefold()
    return any(
        corrupted_message in message
        for corrupted_message in CORRUPTED_DATABASE_ERROR_MESSAGES
    )


def close_connection_if_needed(connection: sqlite3.Connection | None) -> None:
    if connection is not None:
        connection.close()
