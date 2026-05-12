import sqlite3
import unittest
from unittest.mock import patch

from app.ingestion.book_number_assignment import (
    BookNumberAssignment,
    BookNumberAssignmentError,
    assign_book_numbers_for_staged_sources,
)
from app.storage.committed_sources import NewCommittedSource, append_committed_source
from app.storage.world_migrations import apply_world_migrations


class BookNumberAssignmentTests(unittest.TestCase):
    def test_new_world_assignment_starts_at_one(self) -> None:
        connection = bootstrap_test_world_database()

        try:
            assignments = assign_book_numbers_for_staged_sources(
                connection,
                ("entry-1", "entry-2"),
            )

            self.assertEqual(
                assignments,
                (
                    BookNumberAssignment("entry-1", 1),
                    BookNumberAssignment("entry-2", 2),
                ),
            )
        finally:
            connection.close()

    def test_existing_world_assignment_appends_after_highest_book_number(self) -> None:
        connection = bootstrap_test_world_database()

        try:
            append_committed_source(connection, make_source("source-1", 1))
            append_committed_source(connection, make_source("source-2", 2))

            assignments = assign_book_numbers_for_staged_sources(
                connection,
                ("entry-1", "entry-2"),
            )

            self.assertEqual(
                assignments,
                (
                    BookNumberAssignment("entry-1", 3),
                    BookNumberAssignment("entry-2", 4),
                ),
            )
        finally:
            connection.close()

    def test_assignment_does_not_fill_old_gaps(self) -> None:
        connection = bootstrap_test_world_database()

        try:
            append_committed_source(connection, make_source("source-1", 1))
            append_committed_source(connection, make_source("source-3", 3))

            assignments = assign_book_numbers_for_staged_sources(
                connection,
                ("entry-1",),
            )

            self.assertEqual(assignments, (BookNumberAssignment("entry-1", 4),))
        finally:
            connection.close()

    def test_assignment_preserves_staged_order(self) -> None:
        connection = bootstrap_test_world_database()

        try:
            assignments = assign_book_numbers_for_staged_sources(
                connection,
                ("entry-3", "entry-1", "entry-2"),
            )

            self.assertEqual(
                assignments,
                (
                    BookNumberAssignment("entry-3", 1),
                    BookNumberAssignment("entry-1", 2),
                    BookNumberAssignment("entry-2", 3),
                ),
            )
        finally:
            connection.close()

    def test_empty_batch_returns_no_assignments_without_mutating_database(self) -> None:
        connection = bootstrap_test_world_database()

        try:
            assignments = assign_book_numbers_for_staged_sources(connection, ())

            self.assertEqual(assignments, ())
            self.assertEqual(count_committed_sources(connection), 0)
        finally:
            connection.close()

    def test_duplicate_staged_ids_are_rejected_and_logged_at_error(self) -> None:
        connection = bootstrap_test_world_database()

        try:
            with patch("app.ingestion.book_number_assignment.logger") as logger:
                with self.assertRaises(BookNumberAssignmentError):
                    assign_book_numbers_for_staged_sources(
                        connection,
                        ("entry-1", "entry-1"),
                    )

            logger.error.assert_called_once_with(
                "Book number assignment failed: %s",
                "Staged source IDs must be unique.",
            )
            self.assertEqual(count_committed_sources(connection), 0)
        finally:
            connection.close()

    def test_proposed_overlap_conflicts_are_rejected_and_logged_at_error(self) -> None:
        connection = bootstrap_test_world_database()

        try:
            with (
                patch(
                    "app.ingestion.book_number_assignment.get_next_book_number",
                    return_value=1,
                ),
                patch("app.ingestion.book_number_assignment.logger") as logger,
            ):
                append_committed_source(connection, make_source("source-1", 1))

                with self.assertRaises(BookNumberAssignmentError):
                    assign_book_numbers_for_staged_sources(connection, ("entry-1",))

            logger.error.assert_called_once_with(
                "Book number assignment failed: %s",
                "Assigned book number range conflicts with committed sources.",
            )
        finally:
            connection.close()

    def test_sqlite_read_failure_logs_error_and_reraises(self) -> None:
        connection = sqlite3.connect(":memory:")

        try:
            with patch("app.ingestion.book_number_assignment.logger") as logger:
                with self.assertRaises(sqlite3.Error):
                    assign_book_numbers_for_staged_sources(connection, ("entry-1",))

            logger.error.assert_called_once()
        finally:
            connection.close()

    def test_assignment_logs_do_not_include_text_filenames_or_paths(self) -> None:
        connection = bootstrap_test_world_database()
        sensitive_entry_id = "private/source-files/local-source.txt"
        source_text = "Do not log this source text."

        try:
            with patch("app.ingestion.book_number_assignment.logger") as logger:
                assign_book_numbers_for_staged_sources(
                    connection,
                    (sensitive_entry_id, source_text),
                )

            log_output = repr(logger.method_calls)
            self.assertIn("Assigned book numbers", log_output)
            self.assertNotIn(sensitive_entry_id, log_output)
            self.assertNotIn("local-source.txt", log_output)
            self.assertNotIn(source_text, log_output)
        finally:
            connection.close()


def bootstrap_test_world_database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    apply_world_migrations(connection)
    return connection


def make_source(source_id: str, book_number: int) -> NewCommittedSource:
    return NewCommittedSource(
        source_id=source_id,
        original_filename=f"{source_id}.pdf",
        stored_path=f"sources/{source_id}.pdf",
        source_file_type="pdf",
        source_hash=f"sha256:{source_id}",
        book_number=book_number,
        committed_at="2026-05-10 18:30:00",
    )


def count_committed_sources(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT count(*) FROM committed_sources").fetchone()
    return row[0]


if __name__ == "__main__":
    unittest.main()
