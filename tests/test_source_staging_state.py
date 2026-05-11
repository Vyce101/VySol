import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ingestion.staging.source_staging_state import (
    SOURCE_ORDER_KIND_COMMITTED,
    SOURCE_ORDER_KIND_STAGED,
    SourceOrderItem,
    SourceReorderValidationError,
    SourceStagingState,
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
        original_state = registry.replace_staging_state(
            "draft-1",
            [make_entry("entry-1", "one.txt"), make_entry("entry-2", "two.txt")],
        )

        with patch("app.ingestion.staging.source_staging_state.logger") as logger:
            with self.assertRaises(SourceReorderValidationError):
                registry.reorder_staging_entries(
                    "draft-1",
                    ["entry-1", "entry-3"],
                )

        self.assertEqual(registry.get_staging_state("draft-1"), original_state)
        logger.warning.assert_called_once()
        logger.error.assert_not_called()

    def test_rejects_reorder_with_duplicate_staged_entries(self) -> None:
        registry = SourceStagingStateRegistry()
        original_state = registry.replace_staging_state(
            "draft-1",
            [make_entry("entry-1", "one.txt"), make_entry("entry-2", "two.txt")],
        )

        with patch("app.ingestion.staging.source_staging_state.logger") as logger:
            with self.assertRaises(SourceReorderValidationError):
                registry.reorder_staging_entries(
                    "draft-1",
                    ["entry-1", "entry-1"],
                )

        self.assertEqual(registry.get_staging_state("draft-1"), original_state)
        logger.warning.assert_called_once()
        logger.error.assert_not_called()

    def test_reorders_existing_world_staged_entries_after_committed_prefix(self) -> None:
        registry = SourceStagingStateRegistry()
        registry.replace_staging_state(
            "existing-world-1",
            [
                make_entry("entry-1", "one.txt"),
                make_entry("entry-2", "two.txt"),
                make_entry("entry-3", "three.txt"),
            ],
        )

        with patch("app.ingestion.staging.source_staging_state.logger") as logger:
            state = registry.reorder_existing_world_staging_entries(
                "existing-world-1",
                ["source-1", "source-2"],
                [
                    committed_item("source-1"),
                    committed_item("source-2"),
                    staged_item("entry-3"),
                    staged_item("entry-1"),
                    staged_item("entry-2"),
                ],
            )

        self.assertEqual(
            [entry.staging_entry_id for entry in state.entries],
            ["entry-3", "entry-1", "entry-2"],
        )
        logger.debug.assert_called_once_with(
            "Reordered temporary source staging entries: %s",
            ((0, "entry-3"), (1, "entry-1"), (2, "entry-2")),
        )

    def test_rejects_existing_world_committed_source_reorder(self) -> None:
        registry = SourceStagingStateRegistry()
        original_state = registry.replace_staging_state(
            "existing-world-1",
            [make_entry("entry-1", "one.txt"), make_entry("entry-2", "two.txt")],
        )

        with patch("app.ingestion.staging.source_staging_state.logger") as logger:
            with self.assertRaises(SourceReorderValidationError):
                registry.reorder_existing_world_staging_entries(
                    "existing-world-1",
                    ["source-1", "source-2"],
                    [
                        committed_item("source-2"),
                        committed_item("source-1"),
                        staged_item("entry-1"),
                        staged_item("entry-2"),
                    ],
                )

        self.assertEqual(registry.get_staging_state("existing-world-1"), original_state)
        logger.warning.assert_called_once()
        logger.error.assert_not_called()

    def test_rejects_existing_world_staged_entry_before_committed_sources(self) -> None:
        registry = SourceStagingStateRegistry()
        original_state = registry.replace_staging_state(
            "existing-world-1",
            [make_entry("entry-1", "one.txt"), make_entry("entry-2", "two.txt")],
        )

        with patch("app.ingestion.staging.source_staging_state.logger") as logger:
            with self.assertRaises(SourceReorderValidationError):
                registry.reorder_existing_world_staging_entries(
                    "existing-world-1",
                    ["source-1", "source-2"],
                    [
                        committed_item("source-1"),
                        staged_item("entry-1"),
                        committed_item("source-2"),
                        staged_item("entry-2"),
                    ],
                )

        self.assertEqual(registry.get_staging_state("existing-world-1"), original_state)
        logger.warning.assert_called_once()
        logger.error.assert_not_called()

    def test_rejects_existing_world_reorder_with_omitted_source(self) -> None:
        registry = SourceStagingStateRegistry()
        original_state = registry.replace_staging_state(
            "existing-world-1",
            [make_entry("entry-1", "one.txt"), make_entry("entry-2", "two.txt")],
        )

        with patch("app.ingestion.staging.source_staging_state.logger") as logger:
            with self.assertRaises(SourceReorderValidationError):
                registry.reorder_existing_world_staging_entries(
                    "existing-world-1",
                    ["source-1"],
                    [
                        committed_item("source-1"),
                        staged_item("entry-2"),
                    ],
                )

        self.assertEqual(registry.get_staging_state("existing-world-1"), original_state)
        logger.warning.assert_called_once()
        logger.error.assert_not_called()

    def test_rejects_existing_world_reorder_with_unknown_source_id(self) -> None:
        registry = SourceStagingStateRegistry()
        original_state = registry.replace_staging_state(
            "existing-world-1",
            [make_entry("entry-1", "one.txt"), make_entry("entry-2", "two.txt")],
        )

        with patch("app.ingestion.staging.source_staging_state.logger") as logger:
            with self.assertRaises(SourceReorderValidationError):
                registry.reorder_existing_world_staging_entries(
                    "existing-world-1",
                    ["source-1"],
                    [
                        committed_item("source-1"),
                        staged_item("entry-1"),
                        staged_item("entry-3"),
                    ],
                )

        self.assertEqual(registry.get_staging_state("existing-world-1"), original_state)
        logger.warning.assert_called_once()
        logger.error.assert_not_called()

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

    def test_removes_existing_world_staged_source_item_only(self) -> None:
        registry = SourceStagingStateRegistry()
        registry.replace_staging_state(
            "existing-world-1",
            [
                make_entry("entry-1", "one.txt"),
                make_entry("entry-2", "two.txt"),
                make_entry("entry-3", "three.txt"),
            ],
        )

        with patch("app.ingestion.staging.source_staging_state.logger") as logger:
            state = registry.remove_existing_world_source_item(
                "existing-world-1",
                staged_item("entry-2"),
            )

        self.assertEqual(
            [entry.staging_entry_id for entry in state.entries],
            ["entry-1", "entry-3"],
        )
        logger.debug.assert_called_once_with(
            "Removed temporary source staging entry: staging_context_id=%s "
            "staging_entry_id=%s count=%s",
            "existing-world-1",
            "entry-2",
            1,
        )
        logger.warning.assert_not_called()
        logger.error.assert_not_called()

    def test_committed_source_removal_attempt_returns_unchanged_state(self) -> None:
        registry = SourceStagingStateRegistry()
        original_state = registry.replace_staging_state(
            "existing-world-1",
            [make_entry("entry-1", "one.txt"), make_entry("entry-2", "two.txt")],
        )

        with patch("app.ingestion.staging.source_staging_state.logger") as logger:
            state = registry.remove_existing_world_source_item(
                "existing-world-1",
                committed_item("source-1"),
            )

        self.assertEqual(state, original_state)
        self.assertEqual(registry.get_staging_state("existing-world-1"), original_state)
        logger.warning.assert_called_once_with(
            "Invalid temporary source removal request: %s",
            "Committed sources cannot be removed before commit.",
        )
        logger.debug.assert_not_called()
        logger.error.assert_not_called()

    def test_invalid_existing_world_source_removal_kind_returns_unchanged_state(
        self,
    ) -> None:
        registry = SourceStagingStateRegistry()
        original_state = registry.replace_staging_state(
            "existing-world-1",
            [make_entry("entry-1", "one.txt")],
        )

        with patch("app.ingestion.staging.source_staging_state.logger") as logger:
            state = registry.remove_existing_world_source_item(
                "existing-world-1",
                SourceOrderItem("unknown", "entry-1"),
            )

        self.assertEqual(state, original_state)
        self.assertEqual(registry.get_staging_state("existing-world-1"), original_state)
        logger.warning.assert_called_once_with(
            "Invalid temporary source removal request: %s",
            "Source removal item kind is invalid.",
        )
        logger.debug.assert_not_called()
        logger.error.assert_not_called()

    def test_malformed_existing_world_source_removal_item_returns_unchanged_state(
        self,
    ) -> None:
        registry = SourceStagingStateRegistry()
        original_state = registry.replace_staging_state(
            "existing-world-1",
            [make_entry("entry-1", "one.txt")],
        )

        with patch("app.ingestion.staging.source_staging_state.logger") as logger:
            state = registry.remove_existing_world_source_item(
                "existing-world-1",
                "entry-1",  # type: ignore[arg-type]
            )

        self.assertEqual(state, original_state)
        self.assertEqual(registry.get_staging_state("existing-world-1"), original_state)
        logger.warning.assert_called_once_with(
            "Invalid temporary source removal request: %s",
            "Source removal item is invalid.",
        )
        logger.debug.assert_not_called()
        logger.error.assert_not_called()

    def test_staging_removal_failure_logs_error_and_reraises(self) -> None:
        registry = SourceStagingStateRegistry()
        original_state = registry.replace_staging_state(
            "existing-world-1",
            [make_entry("entry-1", "one.txt")],
        )

        with (
            patch(
                "app.ingestion.staging.source_staging_state.SourceStagingState",
                side_effect=RuntimeError("remove failed"),
            ),
            patch("app.ingestion.staging.source_staging_state.logger") as logger,
        ):
            with self.assertRaises(RuntimeError):
                registry.remove_existing_world_source_item(
                    "existing-world-1",
                    staged_item("entry-1"),
                )

        self.assertEqual(registry.get_staging_state("existing-world-1"), original_state)
        logger.error.assert_called_once_with(
            "Failed to remove temporary source staging entry.",
            exc_info=True,
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
        self.assertIsNone(
            registry.remove_existing_world_source_item(
                "missing",
                staged_item("entry-1"),
            )
        )
        self.assertIsNone(registry.reorder_staging_entries("missing", ["entry-1"]))
        self.assertIsNone(
            registry.reorder_existing_world_staging_entries(
                "missing",
                ["source-1"],
                [committed_item("source-1"), staged_item("entry-1")],
            )
        )
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
                state = registry.add_source_file_paths("draft-1", [Path("one.txt")])
                registry.remove_existing_world_source_item(
                    "draft-1",
                    staged_item(state.entries[0].staging_entry_id),
                )
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

        logger.debug.assert_any_call(
            "Removed temporary source staging entry: staging_context_id=%s "
            "staging_entry_id=%s count=%s",
            "draft-1",
            "entry-1",
            1,
        )
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


def committed_item(source_id: str) -> SourceOrderItem:
    return SourceOrderItem(SOURCE_ORDER_KIND_COMMITTED, source_id)


def staged_item(staging_entry_id: str) -> SourceOrderItem:
    return SourceOrderItem(SOURCE_ORDER_KIND_STAGED, staging_entry_id)


if __name__ == "__main__":
    unittest.main()
