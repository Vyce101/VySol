from collections.abc import Callable
from dataclasses import dataclass
import sqlite3

from app.logger import get_logger

logger = get_logger()


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


def apply_bootstrap_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS app_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )


def apply_assets_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS assets (
            asset_id TEXT PRIMARY KEY,
            asset_type TEXT NOT NULL CHECK (asset_type IN ('image', 'font')),
            display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
            stored_path TEXT NOT NULL CHECK (length(trim(stored_path)) > 0),
            file_hash TEXT,
            is_built_in INTEGER NOT NULL CHECK (is_built_in IN (0, 1)),
            full_font_name TEXT,
            CHECK (is_built_in = 1 OR length(trim(coalesce(file_hash, ''))) > 0)
        )
        """
    )


MIGRATIONS = (
    Migration(
        version=1,
        name="bootstrap_app_metadata",
        apply=apply_bootstrap_schema,
    ),
    Migration(
        version=2,
        name="create_assets_table",
        apply=apply_assets_schema,
    ),
)


def get_schema_version(connection: sqlite3.Connection) -> int:
    cursor = connection.execute("PRAGMA user_version")
    row = cursor.fetchone()
    if row is None:
        return 0

    return int(row[0])


def apply_migrations(connection: sqlite3.Connection) -> None:
    current_version = get_schema_version(connection)

    for migration in MIGRATIONS:
        if migration.version <= current_version:
            continue

        logger.debug("Applying migration: %s", migration.name)
        try:
            connection.execute("BEGIN")
            migration.apply(connection)
            connection.execute(f"PRAGMA user_version = {migration.version}")
            connection.commit()
        except sqlite3.Error:
            connection.rollback()
            logger.error("Migration failed: %s", migration.name, exc_info=True)
            raise

        current_version = migration.version
        logger.info("Migration applied successfully.")
