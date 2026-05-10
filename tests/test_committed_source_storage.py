import sqlite3
import unittest
from typing import Any
from unittest.mock import patch

from app.storage.committed_sources import (
    CommittedSource,
    CommittedSourceValidationError,
    DuplicateCommittedSourceError,
    NewCommittedSource,
    append_committed_source,
    list_committed_sources,
)
from app.storage.world_migrations import apply_world_migrations, get_world_schema_version


class CommittedSourceStorageTests(unittest.TestCase):
    def test_migration_creates_committed_sources_table(self) -> None:
        connection = bootstrap_test_world_database()

        try:
            table = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = 'committed_sources'
                """
            ).fetchone()

            self.assertIsNotNone(table)
            self.assertEqual(get_world_schema_version(connection), 3)
        finally:
            connection.close()

    def test_appends_and_lists_committed_source_metadata_exactly(self) -> None:
        connection = bootstrap_test_world_database()
        source = make_source()

        try:
            appended_source = append_committed_source(connection, source)

            self.assertEqual(
                appended_source,
                CommittedSource(
                    source_id="source-1",
                    original_filename="volume-one.pdf",
                    stored_path="sources/source-1.pdf",
                    source_file_type="pdf",
                    source_hash="hash-1",
                    book_number=1,
                    committed_at="2026-05-10 18:30:00",
                ),
            )
            self.assertEqual(list_committed_sources(connection), [appended_source])
        finally:
            connection.close()

    def test_lists_committed_sources_in_book_number_order(self) -> None:
        connection = bootstrap_test_world_database()
        third_source = make_source(source_id="source-c", book_number=3)
        first_source = make_source(source_id="source-a", book_number=1)
        second_source = make_source(source_id="source-b", book_number=2)

        try:
            append_committed_source(connection, third_source)
            appended_first_source = append_committed_source(connection, first_source)
            appended_second_source = append_committed_source(connection, second_source)
            appended_third_source = list_committed_sources(connection)[2]

            self.assertEqual(
                list_committed_sources(connection),
                [appended_first_source, appended_second_source, appended_third_source],
            )
        finally:
            connection.close()

    def test_rejects_duplicate_source_id_and_keeps_existing_source(self) -> None:
        connection = bootstrap_test_world_database()

        try:
            existing_source = append_committed_source(connection, make_source())

            with patch("app.storage.committed_sources.logger") as logger:
                with self.assertRaises(DuplicateCommittedSourceError):
                    append_committed_source(
                        connection,
                        make_source(source_id="source-1", book_number=2),
                    )

            self.assertEqual(list_committed_sources(connection), [existing_source])
            logger.warning.assert_called_once_with(
                "Rejected duplicate committed source ID."
            )
        finally:
            connection.close()

    def test_rejects_duplicate_book_number_and_keeps_existing_source(self) -> None:
        connection = bootstrap_test_world_database()

        try:
            existing_source = append_committed_source(connection, make_source())

            with patch("app.storage.committed_sources.logger") as logger:
                with self.assertRaises(DuplicateCommittedSourceError):
                    append_committed_source(
                        connection,
                        make_source(source_id="source-2", book_number=1),
                    )

            self.assertEqual(list_committed_sources(connection), [existing_source])
            logger.warning.assert_called_once_with(
                "Rejected duplicate committed source book number."
            )
        finally:
            connection.close()

    def test_rejects_invalid_source_metadata_and_logs_warning(self) -> None:
        invalid_overrides: tuple[dict[str, Any], ...] = (
            {"source_id": ""},
            {"original_filename": "  "},
            {"stored_path": ""},
            {"source_file_type": ""},
            {"source_hash": ""},
            {"book_number": 0},
            {"book_number": "1"},
            {"committed_at": ""},
        )

        for overrides in invalid_overrides:
            with self.subTest(overrides=overrides):
                connection = bootstrap_test_world_database()

                try:
                    with patch("app.storage.committed_sources.logger") as logger:
                        with self.assertRaises(CommittedSourceValidationError):
                            append_committed_source(connection, make_source(**overrides))

                    self.assertEqual(list_committed_sources(connection), [])
                    logger.warning.assert_called_once()
                finally:
                    connection.close()

    def test_append_database_failure_rolls_back_logs_error_and_reraises(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute(
            """
            CREATE TABLE committed_sources (
                source_id TEXT PRIMARY KEY,
                original_filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                source_file_type TEXT NOT NULL,
                source_hash TEXT NOT NULL CHECK (source_hash = ''),
                book_number INTEGER NOT NULL UNIQUE,
                committed_at TEXT NOT NULL
            )
            """
        )

        try:
            with patch("app.storage.committed_sources.logger") as logger:
                with self.assertRaises(sqlite3.Error):
                    append_committed_source(connection, make_source())

            row_count = connection.execute(
                "SELECT count(*) FROM committed_sources"
            ).fetchone()[0]

            self.assertEqual(row_count, 0)
            logger.error.assert_called_once()
        finally:
            connection.close()

    def test_list_database_failure_logs_error_and_reraises(self) -> None:
        connection = sqlite3.connect(":memory:")

        try:
            with patch("app.storage.committed_sources.logger") as logger:
                with self.assertRaises(sqlite3.Error):
                    list_committed_sources(connection)

            logger.error.assert_called_once()
        finally:
            connection.close()

    def test_logs_append_at_info(self) -> None:
        connection = bootstrap_test_world_database()

        try:
            with patch("app.storage.committed_sources.logger") as logger:
                append_committed_source(connection, make_source())

            logger.info.assert_called_once_with("Appended committed source metadata.")
        finally:
            connection.close()


def bootstrap_test_world_database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    apply_world_migrations(connection)
    return connection


def make_source(**overrides: Any) -> NewCommittedSource:
    values = {
        "source_id": "source-1",
        "original_filename": "volume-one.pdf",
        "stored_path": "sources/source-1.pdf",
        "source_file_type": "pdf",
        "source_hash": "hash-1",
        "book_number": 1,
        "committed_at": "2026-05-10 18:30:00",
    }
    values.update(overrides)
    return NewCommittedSource(**values)


if __name__ == "__main__":
    unittest.main()
