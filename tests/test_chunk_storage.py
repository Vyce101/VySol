import sqlite3
import unittest
from typing import Any
from unittest.mock import patch

from app.storage.chunks import (
    ChunkValidationError,
    DuplicateChunkError,
    NewChunk,
    StoredChunk,
    append_chunks,
    list_chunks,
)
from app.storage.world_migrations import apply_world_migrations, get_world_schema_version


class ChunkStorageTests(unittest.TestCase):
    def test_migration_creates_chunks_table(self) -> None:
        connection = bootstrap_test_world_database()

        try:
            table = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = 'chunks'
                """
            ).fetchone()

            self.assertIsNotNone(table)
            self.assertEqual(get_world_schema_version(connection), 4)
        finally:
            connection.close()

    def test_appends_and_lists_chunks_exactly(self) -> None:
        connection = bootstrap_test_world_database()
        chunk = make_chunk()

        try:
            appended_chunks = append_chunks(connection, [chunk])

            self.assertEqual(
                appended_chunks,
                [
                    StoredChunk(
                        chunk_id="chunk-1",
                        source_id="source-1",
                        book_number=1,
                        chunk_number=1,
                        chunk_text="Final chunk text.",
                        overlap_text="Overlap text.",
                        character_start_offset=10,
                        character_end_offset=27,
                    )
                ],
            )
            self.assertEqual(list_chunks(connection), appended_chunks)
        finally:
            connection.close()

    def test_lists_chunks_in_book_and_chunk_number_order(self) -> None:
        connection = bootstrap_test_world_database()
        third_chunk = make_chunk(chunk_id="chunk-c", book_number=2, chunk_number=1)
        first_chunk = make_chunk(chunk_id="chunk-a", book_number=1, chunk_number=1)
        second_chunk = make_chunk(chunk_id="chunk-b", book_number=1, chunk_number=2)

        try:
            append_chunks(connection, [third_chunk, first_chunk, second_chunk])

            self.assertEqual(
                [chunk.chunk_id for chunk in list_chunks(connection)],
                ["chunk-a", "chunk-b", "chunk-c"],
            )
        finally:
            connection.close()

    def test_accepts_empty_overlap_text_and_missing_offsets(self) -> None:
        connection = bootstrap_test_world_database()
        chunk = make_chunk(
            overlap_text="",
            character_start_offset=None,
            character_end_offset=None,
        )

        try:
            appended_chunk = append_chunks(connection, [chunk])[0]

            self.assertEqual(appended_chunk.overlap_text, "")
            self.assertIsNone(appended_chunk.character_start_offset)
            self.assertIsNone(appended_chunk.character_end_offset)
        finally:
            connection.close()

    def test_rejects_invalid_chunk_metadata_and_logs_warning(self) -> None:
        invalid_overrides: tuple[dict[str, Any], ...] = (
            {"chunk_id": ""},
            {"source_id": "  "},
            {"book_number": 0},
            {"book_number": "1"},
            {"chunk_number": 0},
            {"chunk_number": "1"},
            {"chunk_text": ""},
            {"overlap_text": None},
            {"character_start_offset": -1},
            {"character_start_offset": "0"},
            {"character_end_offset": -1},
            {"character_end_offset": "1"},
            {"character_start_offset": 20, "character_end_offset": 10},
        )

        for overrides in invalid_overrides:
            with self.subTest(overrides=overrides):
                connection = bootstrap_test_world_database()

                try:
                    with patch("app.storage.chunks.logger") as logger:
                        with self.assertRaises(ChunkValidationError):
                            append_chunks(connection, [make_chunk(**overrides)])

                    self.assertEqual(list_chunks(connection), [])
                    logger.warning.assert_called_once()
                finally:
                    connection.close()

    def test_rejects_duplicate_chunk_id_in_batch(self) -> None:
        connection = bootstrap_test_world_database()

        try:
            with patch("app.storage.chunks.logger") as logger:
                with self.assertRaises(DuplicateChunkError):
                    append_chunks(
                        connection,
                        [
                            make_chunk(chunk_id="chunk-1", chunk_number=1),
                            make_chunk(chunk_id="chunk-1", chunk_number=2),
                        ],
                    )

            self.assertEqual(list_chunks(connection), [])
            logger.warning.assert_called_once_with("Rejected duplicate chunk ID.")
        finally:
            connection.close()

    def test_rejects_duplicate_chunk_position_in_batch(self) -> None:
        connection = bootstrap_test_world_database()

        try:
            with patch("app.storage.chunks.logger") as logger:
                with self.assertRaises(DuplicateChunkError):
                    append_chunks(
                        connection,
                        [
                            make_chunk(chunk_id="chunk-1"),
                            make_chunk(chunk_id="chunk-2"),
                        ],
                    )

            self.assertEqual(list_chunks(connection), [])
            logger.warning.assert_called_once_with("Rejected duplicate chunk position.")
        finally:
            connection.close()

    def test_rejects_existing_chunk_id_and_keeps_existing_chunks(self) -> None:
        connection = bootstrap_test_world_database()

        try:
            existing_chunks = append_chunks(connection, [make_chunk()])

            with patch("app.storage.chunks.logger") as logger:
                with self.assertRaises(DuplicateChunkError):
                    append_chunks(
                        connection,
                        [make_chunk(chunk_id="chunk-1", chunk_number=2)],
                    )

            self.assertEqual(list_chunks(connection), existing_chunks)
            logger.warning.assert_called_once_with("Rejected duplicate chunk ID.")
        finally:
            connection.close()

    def test_rejects_existing_chunk_position_and_keeps_existing_chunks(self) -> None:
        connection = bootstrap_test_world_database()

        try:
            existing_chunks = append_chunks(connection, [make_chunk()])

            with patch("app.storage.chunks.logger") as logger:
                with self.assertRaises(DuplicateChunkError):
                    append_chunks(connection, [make_chunk(chunk_id="chunk-2")])

            self.assertEqual(list_chunks(connection), existing_chunks)
            logger.warning.assert_called_once_with("Rejected duplicate chunk position.")
        finally:
            connection.close()

    def test_append_database_failure_rolls_back_logs_error_and_reraises(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute(
            """
            CREATE TABLE chunks (
                chunk_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL CHECK (source_id != 'source-2'),
                book_number INTEGER NOT NULL,
                chunk_number INTEGER NOT NULL,
                chunk_text TEXT NOT NULL,
                overlap_text TEXT NOT NULL,
                character_start_offset INTEGER,
                character_end_offset INTEGER,
                UNIQUE (book_number, chunk_number)
            )
            """
        )

        try:
            with patch("app.storage.chunks.logger") as logger:
                with self.assertRaises(sqlite3.Error):
                    append_chunks(
                        connection,
                        [
                            make_chunk(chunk_id="chunk-1", source_id="source-1"),
                            make_chunk(
                                chunk_id="chunk-2",
                                source_id="source-2",
                                chunk_number=2,
                            ),
                        ],
                    )

            row_count = connection.execute("SELECT count(*) FROM chunks").fetchone()[0]

            self.assertEqual(row_count, 0)
            logger.error.assert_called_once()
        finally:
            connection.close()

    def test_list_database_failure_logs_error_and_reraises(self) -> None:
        connection = sqlite3.connect(":memory:")

        try:
            with patch("app.storage.chunks.logger") as logger:
                with self.assertRaises(sqlite3.Error):
                    list_chunks(connection)

            logger.error.assert_called_once()
        finally:
            connection.close()

    def test_logs_batch_summary_without_text_content(self) -> None:
        connection = bootstrap_test_world_database()

        try:
            with patch("app.storage.chunks.logger") as logger:
                append_chunks(
                    connection,
                    [
                        make_chunk(
                            chunk_text="Never log this chunk text.",
                            overlap_text="Never log this overlap text.",
                        )
                    ],
                )
                list_chunks(connection)

            log_output = repr(logger.method_calls)
            self.assertIn("chunk-1", log_output)
            self.assertNotIn("Never log this chunk text.", log_output)
            self.assertNotIn("Never log this overlap text.", log_output)
        finally:
            connection.close()


def bootstrap_test_world_database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    apply_world_migrations(connection)
    return connection


def make_chunk(**overrides: Any) -> NewChunk:
    values = {
        "chunk_id": "chunk-1",
        "source_id": "source-1",
        "book_number": 1,
        "chunk_number": 1,
        "chunk_text": "Final chunk text.",
        "overlap_text": "Overlap text.",
        "character_start_offset": 10,
        "character_end_offset": 27,
    }
    values.update(overrides)
    return NewChunk(**values)


if __name__ == "__main__":
    unittest.main()
