import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from app.draft_worlds.registry import DraftWorldRegistry
from app.draft_worlds.splitter_settings import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_MAX_LOOKBACK_SIZE,
    DEFAULT_OVERLAP_SIZE,
    SplitterSettings,
    create_default_splitter_settings,
)
from app.storage.database import bootstrap_global_database, close_global_connection
from app.storage.migrations import get_schema_version


class DraftWorldSplitterDefaultsTests(unittest.TestCase):
    def tearDown(self) -> None:
        close_global_connection()

    def test_creates_default_splitter_settings_as_character_counts(self) -> None:
        splitter_settings = create_default_splitter_settings()

        self.assertEqual(splitter_settings.chunk_size, DEFAULT_CHUNK_SIZE)
        self.assertEqual(splitter_settings.max_lookback_size, DEFAULT_MAX_LOOKBACK_SIZE)
        self.assertEqual(splitter_settings.overlap_size, DEFAULT_OVERLAP_SIZE)
        self.assertIsInstance(splitter_settings.chunk_size, int)
        self.assertIsInstance(splitter_settings.max_lookback_size, int)
        self.assertIsInstance(splitter_settings.overlap_size, int)

    def test_new_draft_world_starts_with_default_splitter_settings(self) -> None:
        registry = DraftWorldRegistry()

        draft_world = registry.create_draft_world()

        UUID(draft_world.draft_id)
        self.assertEqual(
            draft_world.splitter_settings,
            SplitterSettings(
                chunk_size=4000,
                max_lookback_size=1000,
                overlap_size=400,
            ),
        )
        self.assertEqual(
            registry.get_draft_world(draft_world.draft_id),
            draft_world,
        )

    def test_updated_draft_splitter_settings_remain_in_memory_until_discarded(
        self,
    ) -> None:
        registry = DraftWorldRegistry()
        draft_world = registry.create_draft_world()
        updated_settings = SplitterSettings(
            chunk_size=0,
            max_lookback_size=-1,
            overlap_size=9001,
        )

        updated_draft_world = registry.update_draft_splitter_settings(
            draft_world.draft_id,
            updated_settings,
        )
        read_draft_world = registry.get_draft_world(draft_world.draft_id)
        discarded_draft_world = registry.discard_draft_world(draft_world.draft_id)

        self.assertEqual(updated_draft_world.splitter_settings, updated_settings)
        self.assertEqual(read_draft_world, updated_draft_world)
        self.assertEqual(discarded_draft_world, updated_draft_world)
        self.assertIsNone(registry.get_draft_world(draft_world.draft_id))

    def test_update_and_discard_missing_draft_world_return_none(self) -> None:
        registry = DraftWorldRegistry()
        splitter_settings = SplitterSettings(
            chunk_size=1,
            max_lookback_size=1,
            overlap_size=1,
        )

        self.assertIsNone(
            registry.update_draft_splitter_settings(
                "missing-draft-id",
                splitter_settings,
            )
        )
        self.assertIsNone(registry.discard_draft_world("missing-draft-id"))

    def test_draft_worlds_do_not_change_global_database_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            try:
                database_path = Path(temp_directory) / "app.sqlite"
                connection = bootstrap_global_database(database_path)
                registry = DraftWorldRegistry()

                registry.create_draft_world()
                draft_table = connection.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                        AND (name LIKE '%draft%' OR name LIKE '%splitter%')
                    """
                ).fetchone()

                self.assertEqual(get_schema_version(connection), 4)
                self.assertIsNone(draft_table)
            finally:
                close_global_connection()

    def test_logs_default_initialization_failure_at_error(self) -> None:
        registry = DraftWorldRegistry()

        with patch(
            "app.draft_worlds.registry.create_default_splitter_settings",
            side_effect=RuntimeError("defaults unavailable"),
        ):
            with patch("app.draft_worlds.registry.logger") as logger:
                with self.assertRaises(RuntimeError):
                    registry.create_draft_world()

        logger.error.assert_called_once()

    def test_failed_default_initialization_does_not_create_draft_world(self) -> None:
        registry = DraftWorldRegistry()

        with patch(
            "app.draft_worlds.registry.create_default_splitter_settings",
            side_effect=sqlite3.Error("defaults unavailable"),
        ):
            with patch("app.draft_worlds.registry.logger"):
                with self.assertRaises(sqlite3.Error):
                    registry.create_draft_world()

        self.assertEqual(registry._draft_worlds, {})


if __name__ == "__main__":
    unittest.main()
