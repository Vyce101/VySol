from collections.abc import Callable
from dataclasses import dataclass
import sqlite3

from app.logger import get_logger

logger = get_logger()


@dataclass(frozen=True)
class WorldMigration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


def apply_world_metadata_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS world_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )


def apply_world_splitter_settings_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS world_splitter_settings (
            settings_id INTEGER PRIMARY KEY CHECK (settings_id = 1),
            chunk_size INTEGER NOT NULL CHECK (chunk_size >= 1),
            max_lookback_size INTEGER NOT NULL CHECK (max_lookback_size >= 0),
            overlap_size INTEGER NOT NULL CHECK (overlap_size >= 0),
            splitter_version TEXT NOT NULL CHECK (length(trim(splitter_version)) > 0),
            is_locked INTEGER NOT NULL CHECK (is_locked IN (0, 1)),
            CHECK (max_lookback_size < chunk_size)
        )
        """
    )


def apply_committed_sources_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS committed_sources (
            source_id TEXT PRIMARY KEY CHECK (length(trim(source_id)) > 0),
            original_filename TEXT NOT NULL CHECK (length(trim(original_filename)) > 0),
            stored_path TEXT NOT NULL CHECK (length(trim(stored_path)) > 0),
            source_file_type TEXT NOT NULL CHECK (length(trim(source_file_type)) > 0),
            source_hash TEXT NOT NULL CHECK (length(trim(source_hash)) > 0),
            book_number INTEGER NOT NULL UNIQUE CHECK (book_number >= 1),
            committed_at TEXT NOT NULL CHECK (length(trim(committed_at)) > 0)
        )
        """
    )


def apply_chunks_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id TEXT PRIMARY KEY CHECK (length(trim(chunk_id)) > 0),
            source_id TEXT NOT NULL CHECK (length(trim(source_id)) > 0),
            book_number INTEGER NOT NULL CHECK (book_number >= 1),
            chunk_number INTEGER NOT NULL CHECK (chunk_number >= 1),
            chunk_text TEXT NOT NULL CHECK (length(trim(chunk_text)) > 0),
            overlap_text TEXT NOT NULL,
            character_start_offset INTEGER CHECK (
                character_start_offset IS NULL OR character_start_offset >= 0
            ),
            character_end_offset INTEGER CHECK (
                character_end_offset IS NULL OR character_end_offset >= 0
            ),
            UNIQUE (book_number, chunk_number),
            CHECK (
                character_start_offset IS NULL
                OR character_end_offset IS NULL
                OR character_end_offset >= character_start_offset
            )
        )
        """
    )


WORLD_MIGRATIONS = (
    WorldMigration(
        version=1,
        name="bootstrap_world_metadata",
        apply=apply_world_metadata_schema,
    ),
    WorldMigration(
        version=2,
        name="create_world_splitter_settings",
        apply=apply_world_splitter_settings_schema,
    ),
    WorldMigration(
        version=3,
        name="create_committed_sources",
        apply=apply_committed_sources_schema,
    ),
    WorldMigration(
        version=4,
        name="create_chunks",
        apply=apply_chunks_schema,
    ),
)


def get_world_schema_version(connection: sqlite3.Connection) -> int:
    cursor = connection.execute("PRAGMA user_version")
    row = cursor.fetchone()
    if row is None:
        return 0

    return int(row[0])


def apply_world_migrations(connection: sqlite3.Connection) -> None:
    current_version = get_world_schema_version(connection)

    for migration in WORLD_MIGRATIONS:
        if migration.version <= current_version:
            continue

        logger.debug("Applying world database migration: %s", migration.name)
        try:
            connection.execute("BEGIN")
            migration.apply(connection)
            connection.execute(f"PRAGMA user_version = {migration.version}")
            connection.commit()
        except sqlite3.Error:
            connection.rollback()
            logger.error(
                "World database migration failed: %s",
                migration.name,
                exc_info=True,
            )
            raise

        current_version = migration.version
        logger.info("World database migration applied successfully.")
