from collections.abc import Iterator
from contextlib import contextmanager
import inspect
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from app.storage.world_databases import (
    bootstrap_world_database,
    open_world_database,
    resolve_world_database_path,
)
from app.storage.world_folders import WorldFolderValidationError
from app.storage.world_migrations import (
    WorldMigration,
    apply_world_migrations,
    get_world_schema_version,
)


class WorldDatabaseBootstrapTests(unittest.TestCase):
    def test_resolves_world_database_inside_uuid_world_folder(self) -> None:
        with patched_repo_root() as repo_root:
            world_id = str(uuid4())

            database_path = resolve_world_database_path(world_id)

            self.assertEqual(
                database_path,
                repo_root / "user" / "worlds" / world_id / "world.sqlite",
            )

    def test_bootstrap_creates_world_folder_and_database(self) -> None:
        with patched_repo_root() as repo_root:
            world_id = str(uuid4())

            with close_after_test(bootstrap_world_database(world_id)) as connection:
                database_path = repo_root / "user" / "worlds" / world_id / "world.sqlite"

                self.assertTrue(database_path.exists())
                self.assertIsInstance(connection, sqlite3.Connection)

    def test_bootstrap_applies_world_schema_version(self) -> None:
        with patched_repo_root():
            with close_after_test(bootstrap_world_database(str(uuid4()))) as connection:
                self.assertEqual(get_world_schema_version(connection), 4)

    def test_bootstrap_returns_usable_row_connection(self) -> None:
        with patched_repo_root():
            with close_after_test(bootstrap_world_database(str(uuid4()))) as connection:
                connection.execute(
                    "INSERT INTO world_metadata (key, value) VALUES (?, ?)",
                    ("bootstrap_test", "ok"),
                )
                row = connection.execute(
                    "SELECT value FROM world_metadata WHERE key = ?",
                    ("bootstrap_test",),
                ).fetchone()

                self.assertEqual(row["value"], "ok")

    def test_open_world_database_uses_world_id_helper(self) -> None:
        with patched_repo_root():
            with close_after_test(open_world_database(str(uuid4()))) as connection:
                self.assertEqual(get_world_schema_version(connection), 4)

    def test_existing_world_database_opens_without_reapplying_migration(self) -> None:
        with patched_repo_root():
            world_id = str(uuid4())
            with close_after_test(bootstrap_world_database(world_id)) as connection:
                connection.execute(
                    "INSERT INTO world_metadata (key, value) VALUES (?, ?)",
                    ("existing", "kept"),
                )
                connection.commit()

            with close_after_test(bootstrap_world_database(world_id)) as connection:
                row = connection.execute(
                    "SELECT value FROM world_metadata WHERE key = ?",
                    ("existing",),
                ).fetchone()

                self.assertEqual(row["value"], "kept")
                self.assertEqual(get_world_schema_version(connection), 4)

    def test_helpers_accept_only_world_id_argument(self) -> None:
        helper_functions = (
            resolve_world_database_path,
            bootstrap_world_database,
            open_world_database,
        )

        for helper_function in helper_functions:
            with self.subTest(helper_function=helper_function.__name__):
                self.assertEqual(
                    tuple(inspect.signature(helper_function).parameters),
                    ("world_id",),
                )

    def test_rejects_display_name_as_world_id_and_creates_no_database(self) -> None:
        with patched_repo_root() as repo_root:
            with self.assertRaises(WorldFolderValidationError):
                bootstrap_world_database("Naruto")

            self.assertFalse((repo_root / "user" / "worlds").exists())

    def test_logs_open_failure_and_reraises(self) -> None:
        with patched_repo_root() as repo_root:
            worlds_path = repo_root / "user" / "worlds"
            worlds_path.parent.mkdir(parents=True)
            worlds_path.write_text("not a folder", encoding="utf-8")

            with patch("app.storage.world_databases.logger") as logger:
                with self.assertRaises(OSError):
                    bootstrap_world_database(str(uuid4()))

            logger.error.assert_called_once()

    def test_logs_migration_failure_and_reraises(self) -> None:
        def fail_migration(connection: sqlite3.Connection) -> None:
            raise sqlite3.OperationalError("migration failed")

        failing_migrations = (
            WorldMigration(
                version=1,
                name="failing_world_migration",
                apply=fail_migration,
            ),
        )

        with patched_repo_root():
            with patch(
                "app.storage.world_migrations.WORLD_MIGRATIONS",
                failing_migrations,
            ):
                with patch("app.storage.world_databases.logger") as logger:
                    with self.assertRaises(sqlite3.OperationalError):
                        bootstrap_world_database(str(uuid4()))

            logger.error.assert_called_once()

    def test_logs_corrupted_world_database_as_critical(self) -> None:
        with patched_repo_root():
            world_id = str(uuid4())
            database_path = resolve_world_database_path(world_id)
            database_path.parent.mkdir(parents=True)
            database_path.write_text("not a sqlite database", encoding="utf-8")

            with patch("app.storage.world_databases.logger") as logger:
                with self.assertRaises(sqlite3.DatabaseError):
                    bootstrap_world_database(world_id)

            logger.critical.assert_called_once()

    def test_world_migrations_apply_in_version_order(self) -> None:
        applied_migrations: list[str] = []
        connection = sqlite3.connect(":memory:")

        def apply_first_migration(connection: sqlite3.Connection) -> None:
            applied_migrations.append("first")

        def apply_second_migration(connection: sqlite3.Connection) -> None:
            applied_migrations.append("second")

        migrations = (
            WorldMigration(1, "first_world_test_migration", apply_first_migration),
            WorldMigration(2, "second_world_test_migration", apply_second_migration),
        )

        try:
            with patch("app.storage.world_migrations.WORLD_MIGRATIONS", migrations):
                apply_world_migrations(connection)

            self.assertEqual(applied_migrations, ["first", "second"])
            self.assertEqual(get_world_schema_version(connection), 2)
        finally:
            connection.close()


class patched_repo_root:
    def __enter__(self) -> Path:
        self._temp_directory = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._temp_directory.name)
        self._patcher = patch("app.storage.paths.REPO_ROOT", self.repo_root)
        self._patcher.start()
        return self.repo_root

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self._patcher.stop()
        self._temp_directory.cleanup()


@contextmanager
def close_after_test(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield connection
    finally:
        connection.close()


if __name__ == "__main__":
    unittest.main()
