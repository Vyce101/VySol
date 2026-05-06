from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from app.storage.database import bootstrap_global_database, close_global_connection
from app.storage.migrations import apply_migrations, get_schema_version
from app.storage.worlds import (
    CommittedWorldUpdate,
    DuplicateCommittedWorldDisplayNameError,
    NewCommittedWorld,
    create_committed_world,
    get_committed_world,
    list_committed_worlds,
    update_committed_world,
)


class CommittedWorldStorageTests(unittest.TestCase):
    def tearDown(self) -> None:
        close_global_connection()

    def test_migration_creates_worlds_table(self) -> None:
        connection = sqlite3.connect(":memory:")

        try:
            apply_migrations(connection)
            table = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = 'worlds'
                """
            ).fetchone()

            self.assertIsNotNone(table)
            self.assertEqual(get_schema_version(connection), 3)
        finally:
            connection.close()

    def test_creates_and_reads_committed_world(self) -> None:
        with bootstrap_test_database() as connection:
            created_world = create_committed_world(
                NewCommittedWorld(
                    display_name="Naruto",
                    description="Hidden Leaf campaign",
                    background_asset_id="builtin-image-main-world",
                    font_asset_id="builtin-font-inter",
                ),
                connection,
            )
            read_world = get_committed_world(created_world.world_id, connection)

            UUID(created_world.world_id)
            self.assertEqual(read_world, created_world)

    def test_preserves_display_name_exactly_as_entered(self) -> None:
        with bootstrap_test_database() as connection:
            created_world = create_committed_world(
                NewCommittedWorld(
                    display_name="  Naruto Shippuden  ",
                    background_asset_id="builtin-image-main-world",
                    font_asset_id="builtin-font-inter",
                ),
                connection,
            )

            self.assertEqual(created_world.display_name, "  Naruto Shippuden  ")

    def test_updates_committed_world_and_clears_description(self) -> None:
        with bootstrap_test_database() as connection:
            created_world = create_committed_world(
                NewCommittedWorld(
                    display_name="Naruto",
                    description="Original description",
                    background_asset_id="builtin-image-main-world",
                    font_asset_id="builtin-font-inter",
                ),
                connection,
            )

            updated_world = update_committed_world(
                created_world.world_id,
                CommittedWorldUpdate(
                    display_name="Bleach",
                    background_asset_id="builtin-image-neon-city",
                    font_asset_id="builtin-font-cinzel-bold",
                ),
                connection,
            )

            self.assertEqual(updated_world.world_id, created_world.world_id)
            self.assertEqual(updated_world.display_name, "Bleach")
            self.assertIsNone(updated_world.description)
            self.assertEqual(updated_world.background_asset_id, "builtin-image-neon-city")
            self.assertEqual(updated_world.font_asset_id, "builtin-font-cinzel-bold")
            self.assertEqual(
                get_committed_world(created_world.world_id, connection),
                updated_world,
            )

    def test_update_returns_none_when_world_is_missing(self) -> None:
        with bootstrap_test_database() as connection:
            updated_world = update_committed_world(
                "missing-world-id",
                CommittedWorldUpdate(
                    display_name="Naruto",
                    background_asset_id="builtin-image-main-world",
                    font_asset_id="builtin-font-inter",
                ),
                connection,
            )

            self.assertIsNone(updated_world)

    def test_update_missing_world_returns_none_before_duplicate_check(self) -> None:
        with bootstrap_test_database() as connection:
            create_committed_world(
                NewCommittedWorld(
                    display_name="Naruto",
                    background_asset_id="builtin-image-main-world",
                    font_asset_id="builtin-font-inter",
                ),
                connection,
            )

            updated_world = update_committed_world(
                "missing-world-id",
                CommittedWorldUpdate(
                    display_name="naruto",
                    background_asset_id="builtin-image-main-world",
                    font_asset_id="builtin-font-inter",
                ),
                connection,
            )

            self.assertIsNone(updated_world)

    def test_lists_committed_worlds_in_stable_display_order(self) -> None:
        with bootstrap_test_database() as connection:
            second_world = create_committed_world(
                NewCommittedWorld(
                    display_name="Zeta",
                    background_asset_id="builtin-image-main-world",
                    font_asset_id="builtin-font-inter",
                ),
                connection,
            )
            first_world = create_committed_world(
                NewCommittedWorld(
                    display_name="Alpha",
                    background_asset_id="builtin-image-main-world",
                    font_asset_id="builtin-font-inter",
                ),
                connection,
            )

            self.assertEqual(
                list_committed_worlds(connection),
                [first_world, second_world],
            )

    def test_rejects_case_insensitive_duplicate_display_name_and_logs_warning(
        self,
    ) -> None:
        with bootstrap_test_database() as connection:
            create_committed_world(
                NewCommittedWorld(
                    display_name="Naruto",
                    background_asset_id="builtin-image-main-world",
                    font_asset_id="builtin-font-inter",
                ),
                connection,
            )

            with patch("app.storage.worlds.logger") as logger:
                with self.assertRaises(DuplicateCommittedWorldDisplayNameError):
                    create_committed_world(
                        NewCommittedWorld(
                            display_name="naruto",
                            background_asset_id="builtin-image-main-world",
                            font_asset_id="builtin-font-inter",
                        ),
                        connection,
                    )

            logger.warning.assert_called_once()

    def test_rejects_update_to_case_insensitive_duplicate_display_name(self) -> None:
        with bootstrap_test_database() as connection:
            create_committed_world(
                NewCommittedWorld(
                    display_name="Naruto",
                    background_asset_id="builtin-image-main-world",
                    font_asset_id="builtin-font-inter",
                ),
                connection,
            )
            bleach_world = create_committed_world(
                NewCommittedWorld(
                    display_name="Bleach",
                    background_asset_id="builtin-image-main-world",
                    font_asset_id="builtin-font-inter",
                ),
                connection,
            )

            with self.assertRaises(DuplicateCommittedWorldDisplayNameError):
                update_committed_world(
                    bleach_world.world_id,
                    CommittedWorldUpdate(
                        display_name="NARUTO",
                        background_asset_id="builtin-image-main-world",
                        font_asset_id="builtin-font-inter",
                    ),
                    connection,
                )

    def test_logs_read_database_failure_and_reraises(self) -> None:
        connection = sqlite3.connect(":memory:")

        try:
            with patch("app.storage.worlds.logger") as logger:
                with self.assertRaises(sqlite3.Error):
                    get_committed_world("missing-world-id", connection)

            logger.error.assert_called_once()
        finally:
            connection.close()

    def test_logs_write_database_failure_and_reraises(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute(
            """
            CREATE TABLE worlds (
                world_id TEXT PRIMARY KEY,
                display_name_key TEXT UNIQUE
            )
            """
        )

        try:
            with patch("app.storage.worlds.logger") as logger:
                with self.assertRaises(sqlite3.Error):
                    create_committed_world(
                        NewCommittedWorld(
                            display_name="Naruto",
                            background_asset_id="builtin-image-main-world",
                            font_asset_id="builtin-font-inter",
                        ),
                        connection,
                    )

            logger.error.assert_called_once()
        finally:
            connection.close()


@contextmanager
def bootstrap_test_database() -> Iterator[sqlite3.Connection]:
    with tempfile.TemporaryDirectory() as temp_directory:
        database_path = Path(temp_directory) / "app.sqlite"
        try:
            yield bootstrap_global_database(database_path)
        finally:
            close_global_connection()


if __name__ == "__main__":
    unittest.main()
