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


WORLD_MIGRATIONS = (
    WorldMigration(
        version=1,
        name="bootstrap_world_metadata",
        apply=apply_world_metadata_schema,
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
