import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ingestion.staging.source_staging_state import (
    SourceStagingState,
    SourceStagingStateError,
    SourceStagingStateRegistry,
    TemporarySourceStagingEntry,
)
from app.ingestion.staging.source_type_filter import UNSUPPORTED_SOURCE_TYPE_MESSAGE
from app.storage.database import bootstrap_global_database, close_global_connection
from app.storage.migrations import get_schema_version
from app.storage.world_migrations import apply_world_migrations, get_world_schema_version


class SourceStagingStateTests(unittest.TestCase):
    def tearDown(self) -> None:
        close_global_connection()

    def test_adds_selected_paths_as_ordered_temporary_entries(self) -> None:
        registry = SourceStagingStateRegistry()
        registry.create_staging_context("draft-1")

        with patch(
            "app.ingestion.staging.source_staging_state.uuid4",
            side_effect=("entry-1", "entry-2", "entry-3"),
        ):
            state = registry.add_source_file_paths(
                "draft-1",
                [
                    Path("notes.txt"),
                    Path("outline.docx"),
                    Path("manual.pdf"),
                ],
            )

        self.assertEqual(
            state,
            SourceStagingState(
                staging_context_id="draft-1",
                entries=(
                    TemporarySourceStagingEntry(
                        "entry-1",
                        Path("notes.txt"),
                        "txt",
                        True,
                        None,
                    ),
                    TemporarySourceStagingEntry(
                        "entry-2",
                        Path("outline.docx"),
                        "docx",
                        False,
                        UNSUPPORTED_SOURCE_TYPE_MESSAGE,
                    ),
                    TemporarySourceStagingEntry(
                        "entry-3",
                        Path("manual.pdf"),
                        "pdf",
                        True,
                        None,
                    ),
                ),
            ),
        )

    def test_reorders_entries_by_explicit_existing_entry_ids(self) -> None:
        registry = SourceStagingStateRegistry()
        registry.replace_staging_state(
            "draft-1",
            [
                make_entry("entry-1", "one.txt"),
                make_entry("entry-2", "two.txt"),
                make_entry("entry-3", "three.txt"),
            ],
        )

        state = registry.reorder_staging_entries(
            "draft-1",
            ["entry-3", "entry-1", "entry-2"],
        )

        self.assertEqual(
            [entry.staging_entry_id for entry in state.entries],
            ["entry-3", "entry-1", "entry-2"],
        )

    def test_rejects_reorder_that_does_not_match_existing_entries(self) -> None:
        registry = SourceStagingStateRegistry()
        registry.replace_staging_state(
            "draft-1",
            [make_entry("entry-1", "one.txt"), make_entry("entry-2", "two.txt")],
        )

        with patch("app.ingestion.staging.source_staging_state.logger") as logger:
            with self.assertRaises(SourceStagingStateError):
                registry.reorder_staging_entries(
                    "draft-1",
                    ["entry-1", "entry-3"],
                )

        logger.error.assert_called_once()

    def test_removes_only_the_requested_entry(self) -> None:
        registry = SourceStagingStateRegistry()
        registry.replace_staging_state(
            "existing-world-1",
            [
                make_entry("entry-1", "one.txt"),
                make_entry("entry-2", "two.txt"),
                make_entry("entry-3", "three.txt"),
            ],
        )

        state = registry.remove_staging_entry("existing-world-1", "entry-2")

        self.assertEqual(
            [entry.staging_entry_id for entry in state.entries],
            ["entry-1", "entry-3"],
        )

    def test_discards_context_and_temporary_entries(self) -> None:
        registry = SourceStagingStateRegistry()
        state = registry.replace_staging_state(
            "draft-1",
            [make_entry("entry-1", "one.txt")],
        )

        discarded_state = registry.discard_staging_context("draft-1")

        self.assertEqual(discarded_state, state)
        self.assertIsNone(registry.get_staging_state("draft-1"))

    def test_missing_contexts_return_no_state(self) -> None:
        registry = SourceStagingStateRegistry()

        self.assertIsNone(registry.get_staging_state("missing"))
        self.assertIsNone(registry.add_source_file_paths("missing", [Path("one.txt")]))
        self.assertIsNone(registry.remove_staging_entry("missing", "entry-1"))
        self.assertIsNone(registry.reorder_staging_entries("missing", ["entry-1"]))
        self.assertIsNone(registry.discard_staging_context("missing"))

    def test_entries_do_not_assign_book_number(self) -> None:
        entry = TemporarySourceStagingEntry(
            "entry-1",
            Path("one.txt"),
            "txt",
            True,
            None,
        )

        self.assertFalse(hasattr(entry, "book_number"))

    def test_staging_state_does_not_change_global_or_world_database_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            world_connection = sqlite3.connect(":memory:")
            world_connection.row_factory = sqlite3.Row
            try:
                database_path = Path(temp_directory) / "app.sqlite"
                connection = bootstrap_global_database(database_path)
                apply_world_migrations(world_connection)

                registry = SourceStagingStateRegistry()
                registry.create_staging_context("draft-1")
                registry.add_source_file_paths("draft-1", [Path("one.txt")])
                registry.discard_staging_context("draft-1")

                self.assertEqual(get_schema_version(connection), 5)
                self.assertEqual(get_world_schema_version(world_connection), 4)
                self.assertIsNone(
                    connection.execute(
                        """
                        SELECT name
                        FROM sqlite_master
                        WHERE type = 'table' AND name LIKE '%staging%'
                        """
                    ).fetchone()
                )
                self.assertIsNone(
                    world_connection.execute(
                        """
                        SELECT name
                        FROM sqlite_master
                        WHERE type = 'table' AND name LIKE '%staging%'
                        """
                    ).fetchone()
                )
            finally:
                world_connection.close()
                close_global_connection()

    def test_debug_logging_omits_raw_local_paths(self) -> None:
        source_path = Path("private") / "story.txt"
        registry = SourceStagingStateRegistry()
        registry.create_staging_context("draft-1")

        with patch(
            "app.ingestion.staging.source_staging_state.uuid4",
            return_value="entry-1",
        ):
            with patch("app.ingestion.staging.source_staging_state.logger") as logger:
                registry.add_source_file_paths("draft-1", [source_path])
                registry.remove_staging_entry("draft-1", "entry-1")

        self.assertNotIn(str(source_path), str(logger.method_calls))

    def test_error_logging_omits_raw_local_paths(self) -> None:
        source_path = Path("private") / "story.txt"
        registry = SourceStagingStateRegistry()
        registry.create_staging_context("draft-1")

        with (
            patch(
                "app.ingestion.staging.source_staging_state.build_source_staging_list",
                side_effect=RuntimeError(str(source_path)),
            ),
            patch("app.ingestion.staging.source_staging_state.logger") as logger,
        ):
            with self.assertRaises(RuntimeError):
                registry.add_source_file_paths("draft-1", [source_path])

        logger.error.assert_called_once()
        self.assertNotIn(str(source_path), str(logger.method_calls))


def make_entry(
    staging_entry_id: str,
    source_file_path: str,
) -> TemporarySourceStagingEntry:
    return TemporarySourceStagingEntry(
        staging_entry_id=staging_entry_id,
        source_file_path=Path(source_file_path),
        source_file_type="txt",
        is_valid=True,
        error_message=None,
    )


if __name__ == "__main__":
    unittest.main()
