import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID

from app.draft_worlds.registry import DraftWorldRegistry
from app.draft_worlds.splitter_settings import (
    CURRENT_SPLITTER_VERSION,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_MAX_LOOKBACK_SIZE,
    DEFAULT_OVERLAP_SIZE,
    SplitterSettings,
    SplitterSettingsValidationError,
    create_default_splitter_settings,
    validate_splitter_settings,
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
        self.assertEqual(splitter_settings.splitter_version, CURRENT_SPLITTER_VERSION)
        self.assertIsInstance(splitter_settings.chunk_size, int)
        self.assertIsInstance(splitter_settings.max_lookback_size, int)
        self.assertIsInstance(splitter_settings.overlap_size, int)
        self.assertIsInstance(splitter_settings.splitter_version, str)

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
                splitter_version="1",
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
            splitter_version="1",
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
            splitter_version="1",
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


class SplitterSettingsValidationTests(unittest.TestCase):
    def test_accepts_default_splitter_settings(self) -> None:
        splitter_settings = create_default_splitter_settings()

        validated_settings = validate_splitter_settings(splitter_settings)

        self.assertIs(validated_settings, splitter_settings)

    def test_accepts_boundary_splitter_settings(self) -> None:
        splitter_settings = SplitterSettings(
            chunk_size=1,
            max_lookback_size=0,
            overlap_size=0,
            splitter_version="1",
        )

        validated_settings = validate_splitter_settings(splitter_settings)

        self.assertIs(validated_settings, splitter_settings)

    def test_allows_overlap_size_larger_than_chunk_size(self) -> None:
        splitter_settings = SplitterSettings(
            chunk_size=2,
            max_lookback_size=1,
            overlap_size=9,
            splitter_version="1",
        )

        validated_settings = validate_splitter_settings(splitter_settings)

        self.assertIs(validated_settings, splitter_settings)

    def test_rejects_invalid_chunk_size(self) -> None:
        invalid_values: list[Any] = [0, -1, 1.0, "1", True]

        for invalid_value in invalid_values:
            with self.subTest(invalid_value=invalid_value):
                self.assert_invalid_settings(
                    SplitterSettings(
                        chunk_size=invalid_value,
                        max_lookback_size=0,
                        overlap_size=0,
                        splitter_version="1",
                    )
                )

    def test_rejects_invalid_max_lookback_size(self) -> None:
        invalid_values: list[Any] = [-1, 1.0, "1", True]

        for invalid_value in invalid_values:
            with self.subTest(invalid_value=invalid_value):
                self.assert_invalid_settings(
                    SplitterSettings(
                        chunk_size=2,
                        max_lookback_size=invalid_value,
                        overlap_size=0,
                        splitter_version="1",
                    )
                )

    def test_rejects_max_lookback_size_equal_to_chunk_size(self) -> None:
        self.assert_invalid_settings(
            SplitterSettings(
                chunk_size=2,
                max_lookback_size=2,
                overlap_size=0,
                splitter_version="1",
            )
        )

    def test_rejects_max_lookback_size_larger_than_chunk_size(self) -> None:
        self.assert_invalid_settings(
            SplitterSettings(
                chunk_size=2,
                max_lookback_size=3,
                overlap_size=0,
                splitter_version="1",
            )
        )

    def test_rejects_invalid_overlap_size(self) -> None:
        invalid_values: list[Any] = [-1, 1.0, "1", True]

        for invalid_value in invalid_values:
            with self.subTest(invalid_value=invalid_value):
                self.assert_invalid_settings(
                    SplitterSettings(
                        chunk_size=2,
                        max_lookback_size=1,
                        overlap_size=invalid_value,
                        splitter_version="1",
                    )
                )

    def test_rejects_invalid_splitter_version(self) -> None:
        invalid_values: list[Any] = [None, "", " ", 1, True]

        for invalid_value in invalid_values:
            with self.subTest(invalid_value=invalid_value):
                self.assert_invalid_settings(
                    SplitterSettings(
                        chunk_size=1,
                        max_lookback_size=0,
                        overlap_size=0,
                        splitter_version=invalid_value,
                    )
                )

    def test_rejects_missing_splitter_version(self) -> None:
        splitter_settings = LegacySplitterSettings(
            chunk_size=1,
            max_lookback_size=0,
            overlap_size=0,
        )

        self.assert_invalid_settings(splitter_settings)

    def test_logs_invalid_setting_rejection_at_warning(self) -> None:
        splitter_settings = SplitterSettings(
            chunk_size=0,
            max_lookback_size=0,
            overlap_size=0,
            splitter_version="1",
        )

        with patch("app.draft_worlds.splitter_settings.logger") as logger:
            with self.assertRaises(SplitterSettingsValidationError):
                validate_splitter_settings(splitter_settings)

        logger.warning.assert_called_once()
        logger.error.assert_not_called()

    def test_logs_numeric_setting_values_at_debug(self) -> None:
        splitter_settings = SplitterSettings(
            chunk_size=1,
            max_lookback_size=0,
            overlap_size=0,
            splitter_version="1",
        )

        with patch("app.draft_worlds.splitter_settings.logger") as logger:
            validate_splitter_settings(splitter_settings)

        logger.debug.assert_called_once_with(
            "Validating splitter settings: chunk_size=%s max_lookback_size=%s "
            "overlap_size=%s splitter_version=%s",
            1,
            0,
            0,
            "1",
        )

    def test_logs_unexpected_validation_failure_at_error(self) -> None:
        splitter_settings = SplitterSettings(
            chunk_size=1,
            max_lookback_size=0,
            overlap_size=0,
            splitter_version="1",
        )

        with patch("app.draft_worlds.splitter_settings.logger") as logger:
            with patch(
                "app.draft_worlds.splitter_settings.require_whole_number",
                side_effect=RuntimeError("validation helper unavailable"),
            ):
                with self.assertRaises(RuntimeError):
                    validate_splitter_settings(splitter_settings)

        logger.error.assert_called_once_with(
            "Unexpected splitter settings validation failure.",
            exc_info=True,
        )

    def assert_invalid_settings(self, splitter_settings: Any) -> None:
        with self.assertRaises(SplitterSettingsValidationError):
            validate_splitter_settings(splitter_settings)


class LegacySplitterSettings:
    def __init__(
        self,
        chunk_size: int,
        max_lookback_size: int,
        overlap_size: int,
    ) -> None:
        self.chunk_size = chunk_size
        self.max_lookback_size = max_lookback_size
        self.overlap_size = overlap_size


if __name__ == "__main__":
    unittest.main()
