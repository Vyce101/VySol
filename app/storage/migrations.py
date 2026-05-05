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


MIGRATIONS = (
    Migration(
        version=1,
        name="bootstrap_app_metadata",
        apply=apply_bootstrap_schema,
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
