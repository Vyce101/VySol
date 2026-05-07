import sqlite3
import unittest
from unittest.mock import patch

from app.draft_worlds.splitter_settings import (
    CURRENT_SPLITTER_VERSION,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_MAX_LOOKBACK_SIZE,
    DEFAULT_OVERLAP_SIZE,
)
from app.storage.world_migrations import apply_world_migrations, get_world_schema_version
from app.storage.world_splitter_settings import (
    StoredWorldSplitterSettings,
    create_default_world_splitter_settings,
    get_world_splitter_settings,
    lock_world_splitter_settings,
)


class WorldSplitterSettingsStorageTests(unittest.TestCase):
    def test_migration_creates_world_splitter_settings_table(self) -> None:
        connection = bootstrap_test_world_database()

        try:
            table = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = 'world_splitter_settings'
                """
            ).fetchone()

            self.assertIsNotNone(table)
            self.assertEqual(get_world_schema_version(connection), 2)
        finally:
            connection.close()

    def test_creates_and_reads_default_world_splitter_settings(self) -> None:
        connection = bootstrap_test_world_database()

        try:
            created_settings = create_default_world_splitter_settings(connection)
            read_settings = get_world_splitter_settings(connection)

            self.assertEqual(
                created_settings,
                StoredWorldSplitterSettings(
                    chunk_size=DEFAULT_CHUNK_SIZE,
                    max_lookback_size=DEFAULT_MAX_LOOKBACK_SIZE,
                    overlap_size=DEFAULT_OVERLAP_SIZE,
                    splitter_version=CURRENT_SPLITTER_VERSION,
                    is_locked=False,
                ),
            )
            self.assertEqual(read_settings, created_settings)
        finally:
            connection.close()

    def test_created_world_splitter_settings_are_unlocked(self) -> None:
        connection = bootstrap_test_world_database()

        try:
            created_settings = create_default_world_splitter_settings(connection)

            self.assertFalse(created_settings.is_locked)
        finally:
            connection.close()

    def test_locks_world_splitter_settings_without_changing_values(self) -> None:
        connection = bootstrap_test_world_database()

        try:
            created_settings = create_default_world_splitter_settings(connection)
            locked_settings = lock_world_splitter_settings(connection)

            self.assertEqual(locked_settings.chunk_size, created_settings.chunk_size)
            self.assertEqual(
                locked_settings.max_lookback_size,
                created_settings.max_lookback_size,
            )
            self.assertEqual(locked_settings.overlap_size, created_settings.overlap_size)
            self.assertEqual(
                locked_settings.splitter_version,
                created_settings.splitter_version,
            )
            self.assertTrue(locked_settings.is_locked)
            self.assertEqual(get_world_splitter_settings(connection), locked_settings)
        finally:
            connection.close()

    def test_missing_world_splitter_settings_read_returns_none_and_logs_error(
        self,
    ) -> None:
        connection = bootstrap_test_world_database()

        try:
            with patch("app.storage.world_splitter_settings.logger") as logger:
                read_settings = get_world_splitter_settings(connection)

            self.assertIsNone(read_settings)
            logger.error.assert_called_once_with("Missing world splitter settings.")
        finally:
            connection.close()

    def test_missing_world_splitter_settings_lock_returns_none_and_logs_error(
        self,
    ) -> None:
        connection = bootstrap_test_world_database()

        try:
            with patch("app.storage.world_splitter_settings.logger") as logger:
                locked_settings = lock_world_splitter_settings(connection)

            self.assertIsNone(locked_settings)
            logger.error.assert_called_once_with("Missing world splitter settings.")
        finally:
            connection.close()

    def test_invalid_world_splitter_settings_read_returns_none_and_logs_error(
        self,
    ) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row

        try:
            connection.execute(
                """
                CREATE TABLE world_splitter_settings (
                    chunk_size TEXT NOT NULL,
                    max_lookback_size INTEGER NOT NULL,
                    overlap_size INTEGER NOT NULL,
                    splitter_version TEXT NOT NULL,
                    is_locked INTEGER NOT NULL
                )
                """,
            )
            connection.execute(
                """
                INSERT INTO world_splitter_settings (
                    chunk_size,
                    max_lookback_size,
                    overlap_size,
                    splitter_version,
                    is_locked
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                ("4000", 1000, 400, "1", 0),
            )
            connection.commit()

            with patch("app.storage.world_splitter_settings.logger") as logger:
                read_settings = get_world_splitter_settings(connection)

            self.assertIsNone(read_settings)
            logger.error.assert_called_once_with(
                "Invalid world splitter settings state."
            )
        finally:
            connection.close()

    def test_logs_creation_and_lock_at_info(self) -> None:
        connection = bootstrap_test_world_database()

        try:
            with patch("app.storage.world_splitter_settings.logger") as logger:
                create_default_world_splitter_settings(connection)
                lock_world_splitter_settings(connection)

            logger.info.assert_any_call("Created world splitter settings.")
            logger.info.assert_any_call("Locked world splitter settings.")
        finally:
            connection.close()

    def test_logs_numeric_settings_and_splitter_version_at_debug(self) -> None:
        connection = bootstrap_test_world_database()

        try:
            with patch("app.storage.world_splitter_settings.logger") as logger:
                create_default_world_splitter_settings(connection)
                lock_world_splitter_settings(connection)

            logger.debug.assert_any_call(
                "World splitter settings: chunk_size=%s max_lookback_size=%s "
                "overlap_size=%s splitter_version=%s",
                DEFAULT_CHUNK_SIZE,
                DEFAULT_MAX_LOOKBACK_SIZE,
                DEFAULT_OVERLAP_SIZE,
                CURRENT_SPLITTER_VERSION,
            )
        finally:
            connection.close()

    def test_create_write_failure_rolls_back_logs_error_and_reraises(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute(
            """
            CREATE TABLE world_splitter_settings (
                settings_id INTEGER PRIMARY KEY CHECK (settings_id = 1),
                chunk_size INTEGER NOT NULL CHECK (chunk_size < 0)
            )
            """
        )

        try:
            with patch("app.storage.world_splitter_settings.logger") as logger:
                with self.assertRaises(sqlite3.Error):
                    create_default_world_splitter_settings(connection)

            row_count = connection.execute(
                "SELECT count(*) FROM world_splitter_settings"
            ).fetchone()[0]

            self.assertEqual(row_count, 0)
            logger.error.assert_called_once()
        finally:
            connection.close()

    def test_lock_write_failure_rolls_back_logs_error_and_reraises(self) -> None:
        connection = bootstrap_test_world_database()

        try:
            create_default_world_splitter_settings(connection)
            connection.execute("DROP TABLE world_splitter_settings")
            connection.execute(
                """
                CREATE TABLE world_splitter_settings (
                    settings_id INTEGER PRIMARY KEY CHECK (settings_id = 1),
                    chunk_size INTEGER NOT NULL CHECK (chunk_size >= 1),
                    max_lookback_size INTEGER NOT NULL CHECK (max_lookback_size >= 0),
                    overlap_size INTEGER NOT NULL CHECK (overlap_size >= 0),
                    splitter_version TEXT NOT NULL CHECK (length(trim(splitter_version)) > 0),
                    is_locked INTEGER NOT NULL CHECK (is_locked = 0),
                    CHECK (max_lookback_size < chunk_size)
                )
                """
            )
            connection.execute(
                """
                INSERT INTO world_splitter_settings (
                    settings_id,
                    chunk_size,
                    max_lookback_size,
                    overlap_size,
                    splitter_version,
                    is_locked
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (1, DEFAULT_CHUNK_SIZE, DEFAULT_MAX_LOOKBACK_SIZE, 400, "1", 0),
            )
            connection.commit()

            with patch("app.storage.world_splitter_settings.logger") as logger:
                with self.assertRaises(sqlite3.Error):
                    lock_world_splitter_settings(connection)

            row = connection.execute(
                "SELECT is_locked FROM world_splitter_settings"
            ).fetchone()

            self.assertEqual(row["is_locked"], 0)
            logger.error.assert_called_once()
        finally:
            connection.close()


def bootstrap_test_world_database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    apply_world_migrations(connection)
    return connection


if __name__ == "__main__":
    unittest.main()
