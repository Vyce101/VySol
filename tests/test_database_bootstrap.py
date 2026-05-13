import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from app.storage.database import (
    bootstrap_global_database,
    close_global_connection,
    get_global_connection,
)
from app.storage.migrations import Migration, apply_migrations, get_schema_version


class DatabaseBootstrapTests(unittest.TestCase):
    def tearDown(self) -> None:
        close_global_connection()

    def test_bootstrap_creates_missing_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            try:
                database_path = Path(temp_directory) / "user" / "data" / "app.sqlite"

                connection = bootstrap_global_database(database_path)

                self.assertTrue(database_path.exists())
                self.assertIsInstance(connection, sqlite3.Connection)
            finally:
                close_global_connection()

    def test_bootstrap_applies_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            try:
                database_path = Path(temp_directory) / "app.sqlite"
                connection = bootstrap_global_database(database_path)

                self.assertEqual(get_schema_version(connection), 5)
            finally:
                close_global_connection()

    def test_bootstrap_returns_usable_connection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            try:
                database_path = Path(temp_directory) / "app.sqlite"
                connection = bootstrap_global_database(database_path)

                connection.execute(
                    "INSERT INTO app_metadata (key, value) VALUES (?, ?)",
                    ("bootstrap_test", "ok"),
                )
                row = connection.execute(
                    "SELECT value FROM app_metadata WHERE key = ?",
                    ("bootstrap_test",),
                ).fetchone()

                self.assertEqual(row["value"], "ok")
            finally:
                close_global_connection()

    def test_bootstrapped_connection_can_be_used_from_route_worker_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            try:
                database_path = Path(temp_directory) / "app.sqlite"
                connection = bootstrap_global_database(database_path)
                worker_errors: list[Exception] = []

                def read_from_worker_thread() -> None:
                    try:
                        connection.execute("SELECT COUNT(*) FROM worlds").fetchone()
                    except Exception as error:
                        worker_errors.append(error)

                worker_thread = threading.Thread(target=read_from_worker_thread)
                worker_thread.start()
                worker_thread.join()

                self.assertEqual(worker_errors, [])
            finally:
                close_global_connection()

    def test_global_connection_uses_bootstrapped_connection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            try:
                database_path = Path(temp_directory) / "app.sqlite"
                connection = bootstrap_global_database(database_path)

                self.assertIs(get_global_connection(), connection)
            finally:
                close_global_connection()

    def test_migrations_apply_in_version_order(self) -> None:
        applied_migrations: list[str] = []
        connection = sqlite3.connect(":memory:")

        def apply_first_migration(connection: sqlite3.Connection) -> None:
            applied_migrations.append("first")

        def apply_second_migration(connection: sqlite3.Connection) -> None:
            applied_migrations.append("second")

        migrations = (
            Migration(1, "first_test_migration", apply_first_migration),
            Migration(2, "second_test_migration", apply_second_migration),
        )

        try:
            with patch("app.storage.migrations.MIGRATIONS", migrations):
                apply_migrations(connection)

            self.assertEqual(applied_migrations, ["first", "second"])
            self.assertEqual(get_schema_version(connection), 2)
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
