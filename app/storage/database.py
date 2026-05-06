import sqlite3
from pathlib import Path

from app.logger import get_logger
from app.storage.migrations import apply_migrations, get_schema_version
from app.storage.paths import get_app_database_path

logger = get_logger()
_global_connection: sqlite3.Connection | None = None


def bootstrap_global_database(database_path: Path | None = None) -> sqlite3.Connection:
    path = database_path or get_app_database_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        was_created = not path.exists()
        connection = connect_to_database(path)
        if was_created:
            logger.info("Created global app database.")
        else:
            logger.info("Opened global app database.")

        current_version = get_schema_version(connection)
        logger.debug("Current schema version: %s", current_version)
        apply_migrations(connection)
        logger.info("Database migrations completed.")
        seed_default_asset_references(connection)
    except (OSError, sqlite3.Error):
        logger.error("Recoverable database setup or migration problem.", exc_info=True)
        raise

    set_global_connection(connection)
    return connection


def get_global_connection() -> sqlite3.Connection:
    global _global_connection

    if _global_connection is None:
        return bootstrap_global_database()

    return _global_connection


def close_global_connection() -> None:
    global _global_connection

    if _global_connection is None:
        return

    _global_connection.close()
    _global_connection = None


def connect_to_database(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


def set_global_connection(connection: sqlite3.Connection) -> None:
    global _global_connection

    if _global_connection is not None and _global_connection is not connection:
        _global_connection.close()

    _global_connection = connection


def seed_default_asset_references(connection: sqlite3.Connection) -> None:
    from app.storage.default_assets import seed_default_asset_references as seed_references

    seed_references(connection)
