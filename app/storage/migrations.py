from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import sqlite3

from app.logger import get_logger

logger = get_logger()
LAST_USED_AT_FORMAT = "%Y-%m-%d %H:%M:%S"
LAST_USED_AT_DEFAULT = "1970-01-01 00:00:00"


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


def apply_worlds_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS worlds (
            world_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
            display_name_key TEXT NOT NULL UNIQUE CHECK (length(display_name_key) > 0),
            description TEXT,
            background_asset_id TEXT NOT NULL CHECK (length(trim(background_asset_id)) > 0),
            font_asset_id TEXT NOT NULL CHECK (length(trim(font_asset_id)) > 0)
        )
        """
    )


def apply_world_last_used_at_schema(connection: sqlite3.Connection) -> None:
    last_used_at = datetime.now(timezone.utc).strftime(LAST_USED_AT_FORMAT)
    connection.execute(
        f"""
        ALTER TABLE worlds
        ADD COLUMN last_used_at TEXT NOT NULL DEFAULT '{LAST_USED_AT_DEFAULT}'
        """
    )
    connection.execute(
        """
        UPDATE worlds
        SET last_used_at = ?
        """,
        (last_used_at,),
    )


def apply_asset_original_filename_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        ALTER TABLE assets
        ADD COLUMN original_filename TEXT
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
    Migration(
        version=3,
        name="create_worlds_table",
        apply=apply_worlds_schema,
    ),
    Migration(
        version=4,
        name="add_world_last_used_at",
        apply=apply_world_last_used_at_schema,
    ),
    Migration(
        version=5,
        name="add_asset_original_filename",
        apply=apply_asset_original_filename_schema,
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
