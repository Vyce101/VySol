import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ingestion.staging import (
    DuplicateStagedSourceError,
    HashedStagedSource,
    validate_no_duplicate_staged_source_hashes,
)
from app.ingestion.staging.source_staging_state import TemporarySourceStagingEntry
from app.storage.committed_sources import NewCommittedSource, append_committed_source
from app.storage.world_migrations import apply_world_migrations


class StagedSourceDuplicatePreflightTests(unittest.TestCase):
    def test_allows_unique_staged_hashes_and_preserves_order(self) -> None:
        connection = bootstrap_test_world_database()
        first_source = make_hashed_source("entry-1", "sha256:unique-first")
        second_source = make_hashed_source("entry-2", "sha256:unique-second")

        try:
            validated_sources = validate_no_duplicate_staged_source_hashes(
                connection,
                (first_source, second_source),
            )

            self.assertEqual(validated_sources, (first_source, second_source))
        finally:
            connection.close()

    def test_rejects_staged_hash_matching_committed_source_in_same_world(self) -> None:
        connection = bootstrap_test_world_database()
        source_hash = "sha256:committed-match"

        try:
            append_committed_source(connection, make_committed_source(source_hash))

            with patch("app.ingestion.staging.source_duplicate_preflight.logger") as logger:
                with self.assertRaises(DuplicateStagedSourceError):
                    validate_no_duplicate_staged_source_hashes(
                        connection,
                        (make_hashed_source("entry-1", source_hash),),
                    )

            logger.warning.assert_called_once_with(
                "Rejected duplicate staged source hash in committed sources."
            )
        finally:
            connection.close()

    def test_rejects_duplicate_hashes_inside_staged_batch(self) -> None:
        connection = bootstrap_test_world_database()
        source_hash = "sha256:batch-match"

        try:
            with patch("app.ingestion.staging.source_duplicate_preflight.logger") as logger:
                with self.assertRaises(DuplicateStagedSourceError):
                    validate_no_duplicate_staged_source_hashes(
                        connection,
                        (
                            make_hashed_source("entry-1", source_hash),
                            make_hashed_source("entry-2", source_hash),
                        ),
                    )

            logger.warning.assert_called_once_with(
                "Rejected duplicate staged source hash in batch."
            )
        finally:
            connection.close()

    def test_allows_same_hash_in_different_world_database(self) -> None:
        first_world_connection = bootstrap_test_world_database()
        second_world_connection = bootstrap_test_world_database()
        source_hash = "sha256:world-scoped-match"
        staged_source = make_hashed_source("entry-1", source_hash)

        try:
            append_committed_source(
                first_world_connection,
                make_committed_source(source_hash),
            )

            self.assertEqual(
                validate_no_duplicate_staged_source_hashes(
                    second_world_connection,
                    (staged_source,),
                ),
                (staged_source,),
            )
        finally:
            first_world_connection.close()
            second_world_connection.close()

    def test_empty_batch_returns_empty_tuple_without_database_lookup(self) -> None:
        connection = sqlite3.connect(":memory:")

        try:
            self.assertEqual(
                validate_no_duplicate_staged_source_hashes(connection, []),
                (),
            )
        finally:
            connection.close()

    def test_database_failure_logs_error_and_reraises(self) -> None:
        connection = sqlite3.connect(":memory:")

        try:
            with patch("app.ingestion.staging.source_duplicate_preflight.logger") as logger:
                with self.assertRaises(sqlite3.Error):
                    validate_no_duplicate_staged_source_hashes(
                        connection,
                        (make_hashed_source("entry-1", "sha256:unique-hash"),),
                    )

            logger.error.assert_called_once()
        finally:
            connection.close()

    def test_duplicate_logs_omit_full_hash_paths_filenames_and_contents(self) -> None:
        connection = bootstrap_test_world_database()
        source_contents = "sensitive source text"
        full_hash = "sha256:1234567890abcdef1234567890abcdef"

        with tempfile.TemporaryDirectory() as temp_directory:
            source_path = Path(temp_directory) / "secret-source.txt"
            source_path.write_text(source_contents, encoding="utf-8")

            try:
                with patch(
                    "app.ingestion.staging.source_duplicate_preflight.logger"
                ) as logger:
                    with self.assertRaises(DuplicateStagedSourceError):
                        validate_no_duplicate_staged_source_hashes(
                            connection,
                            (
                                make_hashed_source("entry-1", full_hash, source_path),
                                make_hashed_source("entry-2", full_hash, source_path),
                            ),
                        )

                log_output = repr(logger.method_calls)
                self.assertIn(full_hash[:19], log_output)
                self.assertNotIn(full_hash, log_output)
                self.assertNotIn(str(source_path), log_output)
                self.assertNotIn(source_path.name, log_output)
                self.assertNotIn(source_contents, log_output)
                logger.warning.assert_called_once()
            finally:
                connection.close()


def bootstrap_test_world_database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    apply_world_migrations(connection)
    return connection


def make_committed_source(source_hash: str) -> NewCommittedSource:
    return NewCommittedSource(
        source_id="source-1",
        original_filename="volume-one.pdf",
        stored_path="sources/source-1.pdf",
        source_file_type="pdf",
        source_hash=source_hash,
        book_number=1,
        committed_at="2026-05-10 18:30:00",
    )


def make_hashed_source(
    staging_entry_id: str,
    source_hash: str,
    source_file_path: Path | None = None,
) -> HashedStagedSource:
    return HashedStagedSource(
        staged_source=TemporarySourceStagingEntry(
            staging_entry_id=staging_entry_id,
            source_file_path=source_file_path or Path(f"{staging_entry_id}.txt"),
            source_file_type="txt",
            is_valid=True,
            error_message=None,
        ),
        source_hash=source_hash,
    )


if __name__ == "__main__":
    unittest.main()
