import sqlite3
import unittest
from unittest.mock import patch

from app.draft_worlds.splitter_settings import (
    CURRENT_SPLITTER_VERSION,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_MAX_LOOKBACK_SIZE,
    DEFAULT_OVERLAP_SIZE,
    SplitterSettings,
)
from app.storage.world_migrations import apply_world_migrations, get_world_schema_version
from app.storage.world_splitter_settings import (
    StoredWorldSplitterSettings,
    create_default_world_splitter_settings,
    get_world_splitter_settings,
    lock_world_splitter_settings,
    save_world_splitter_settings,
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
            self.assertEqual(get_world_schema_version(connection), 3)
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

    def test_save_creates_unlocked_world_splitter_settings_when_missing(self) -> None:
        connection = bootstrap_test_world_database()
        splitter_settings = SplitterSettings(
            chunk_size=2000,
            max_lookback_size=500,
            overlap_size=200,
            splitter_version="ignored-caller-version",
        )

        try:
            saved_settings = save_world_splitter_settings(connection, splitter_settings)

            self.assertEqual(
                saved_settings,
                StoredWorldSplitterSettings(
                    chunk_size=2000,
                    max_lookback_size=500,
                    overlap_size=200,
                    splitter_version=CURRENT_SPLITTER_VERSION,
                    is_locked=False,
                ),
            )
            self.assertEqual(get_world_splitter_settings(connection), saved_settings)
        finally:
            connection.close()

    def test_save_updates_existing_unlocked_world_splitter_settings(self) -> None:
        connection = bootstrap_test_world_database()
        initial_settings = SplitterSettings(
            chunk_size=2000,
            max_lookback_size=500,
            overlap_size=200,
            splitter_version="ignored-caller-version",
        )
        updated_settings = SplitterSettings(
            chunk_size=3000,
            max_lookback_size=600,
            overlap_size=300,
            splitter_version="ignored-updated-caller-version",
        )

        try:
            save_world_splitter_settings(connection, initial_settings)
            saved_settings = save_world_splitter_settings(connection, updated_settings)

            self.assertEqual(
                saved_settings,
                StoredWorldSplitterSettings(
                    chunk_size=3000,
                    max_lookback_size=600,
                    overlap_size=300,
                    splitter_version=CURRENT_SPLITTER_VERSION,
                    is_locked=False,
                ),
            )
            self.assertEqual(get_world_splitter_settings(connection), saved_settings)
        finally:
            connection.close()

    def test_save_preserves_existing_splitter_version_when_unlocked(self) -> None:
        connection = bootstrap_test_world_database()
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
            (1, 2000, 500, 200, "legacy-backend-version", 0),
        )
        connection.commit()
        updated_settings = SplitterSettings(
            chunk_size=3000,
            max_lookback_size=600,
            overlap_size=300,
            splitter_version="ignored-caller-version",
        )

        try:
            saved_settings = save_world_splitter_settings(connection, updated_settings)

            self.assertEqual(
                saved_settings,
                StoredWorldSplitterSettings(
                    chunk_size=3000,
                    max_lookback_size=600,
                    overlap_size=300,
                    splitter_version="legacy-backend-version",
                    is_locked=False,
                ),
            )
            self.assertEqual(get_world_splitter_settings(connection), saved_settings)
        finally:
            connection.close()

    def test_save_matching_locked_settings_returns_existing_settings(self) -> None:
        connection = bootstrap_test_world_database()
        splitter_settings = SplitterSettings(
            chunk_size=2000,
            max_lookback_size=500,
            overlap_size=200,
            splitter_version="ignored-caller-version",
        )

        try:
            save_world_splitter_settings(connection, splitter_settings)
            locked_settings = lock_world_splitter_settings(connection)

            with patch("app.storage.world_splitter_settings.logger") as logger:
                saved_settings = save_world_splitter_settings(
                    connection,
                    splitter_settings,
                )

            self.assertEqual(saved_settings, locked_settings)
            self.assertEqual(get_world_splitter_settings(connection), locked_settings)
            logger.warning.assert_not_called()
        finally:
            connection.close()

    def test_save_different_locked_settings_warns_and_keeps_existing_settings(
        self,
    ) -> None:
        connection = bootstrap_test_world_database()
        locked_request = SplitterSettings(
            chunk_size=2000,
            max_lookback_size=500,
            overlap_size=200,
            splitter_version="ignored-caller-version",
        )
        different_request = SplitterSettings(
            chunk_size=3000,
            max_lookback_size=600,
            overlap_size=300,
            splitter_version="ignored-updated-caller-version",
        )

        try:
            save_world_splitter_settings(connection, locked_request)
            locked_settings = lock_world_splitter_settings(connection)

            with patch("app.storage.world_splitter_settings.logger") as logger:
                saved_settings = save_world_splitter_settings(
                    connection,
                    different_request,
                )

            self.assertEqual(saved_settings, locked_settings)
            self.assertEqual(get_world_splitter_settings(connection), locked_settings)
            logger.warning.assert_called_once_with(
                "Rejected locked world splitter settings update."
            )
        finally:
            connection.close()

    def test_different_worlds_lock_different_splitter_settings(self) -> None:
        first_connection = bootstrap_test_world_database()
        second_connection = bootstrap_test_world_database()
        first_settings = SplitterSettings(
            chunk_size=2000,
            max_lookback_size=500,
            overlap_size=200,
            splitter_version="ignored-caller-version",
        )
        second_settings = SplitterSettings(
            chunk_size=3000,
            max_lookback_size=600,
            overlap_size=300,
            splitter_version="ignored-updated-caller-version",
        )

        try:
            save_world_splitter_settings(first_connection, first_settings)
            save_world_splitter_settings(second_connection, second_settings)

            first_locked_settings = lock_world_splitter_settings(first_connection)
            second_locked_settings = lock_world_splitter_settings(second_connection)

            self.assertNotEqual(first_locked_settings, second_locked_settings)
            self.assertEqual(
                first_locked_settings,
                StoredWorldSplitterSettings(
                    chunk_size=2000,
                    max_lookback_size=500,
                    overlap_size=200,
                    splitter_version=CURRENT_SPLITTER_VERSION,
                    is_locked=True,
                ),
            )
            self.assertEqual(
                second_locked_settings,
                StoredWorldSplitterSettings(
                    chunk_size=3000,
                    max_lookback_size=600,
                    overlap_size=300,
                    splitter_version=CURRENT_SPLITTER_VERSION,
                    is_locked=True,
                ),
            )
        finally:
            first_connection.close()
            second_connection.close()

    def test_relocking_world_splitter_settings_does_not_log_first_lock_again(
        self,
    ) -> None:
        connection = bootstrap_test_world_database()

        try:
            create_default_world_splitter_settings(connection)

            with patch("app.storage.world_splitter_settings.logger") as logger:
                first_locked_settings = lock_world_splitter_settings(connection)
                second_locked_settings = lock_world_splitter_settings(connection)

            lock_messages = [
                call
                for call in logger.info.call_args_list
                if call.args == ("Locked world splitter settings.",)
            ]
            self.assertEqual(first_locked_settings, second_locked_settings)
            self.assertEqual(len(lock_messages), 1)
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

    def test_save_write_failure_rolls_back_logs_error_and_reraises(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute(
            """
            CREATE TABLE world_splitter_settings (
                settings_id INTEGER PRIMARY KEY CHECK (settings_id = 1),
                chunk_size INTEGER NOT NULL CHECK (chunk_size < 0),
                max_lookback_size INTEGER NOT NULL CHECK (max_lookback_size >= 0),
                overlap_size INTEGER NOT NULL CHECK (overlap_size >= 0),
                splitter_version TEXT NOT NULL CHECK (length(trim(splitter_version)) > 0),
                is_locked INTEGER NOT NULL CHECK (is_locked IN (0, 1)),
                CHECK (max_lookback_size < chunk_size)
            )
            """
        )
        splitter_settings = SplitterSettings(
            chunk_size=2000,
            max_lookback_size=500,
            overlap_size=200,
            splitter_version="ignored-caller-version",
        )

        try:
            with patch("app.storage.world_splitter_settings.logger") as logger:
                with self.assertRaises(sqlite3.Error):
                    save_world_splitter_settings(connection, splitter_settings)

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
