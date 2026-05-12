import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ingestion.staging import HashedStagedSource, hash_staged_source_files
from app.ingestion.staging.source_staging_state import TemporarySourceStagingEntry


class StagedSourceHashPreflightTests(unittest.TestCase):
    def test_hashes_staged_sources_in_order_with_original_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            first_path = Path(temp_directory) / "first.txt"
            second_path = Path(temp_directory) / "second.pdf"
            first_contents = b"First source."
            second_contents = b"%PDF source bytes"
            first_path.write_bytes(first_contents)
            second_path.write_bytes(second_contents)
            first_entry = make_entry("entry-1", first_path, "txt")
            second_entry = make_entry("entry-2", second_path, "pdf")

            hashed_sources = hash_staged_source_files((first_entry, second_entry))

        self.assertEqual(
            hashed_sources,
            (
                HashedStagedSource(first_entry, expected_sha256_hash(first_contents)),
                HashedStagedSource(second_entry, expected_sha256_hash(second_contents)),
            ),
        )

    def test_empty_batch_returns_empty_tuple(self) -> None:
        self.assertEqual(hash_staged_source_files([]), ())

    def test_logs_completion_without_file_contents_or_full_paths(self) -> None:
        file_contents = b"sensitive source text"

        with tempfile.TemporaryDirectory() as temp_directory:
            source_path = Path(temp_directory) / "source.txt"
            source_path.write_bytes(file_contents)
            entries = (make_entry("entry-1", source_path, "txt"),)

            with patch("app.ingestion.staging.source_hash_preflight.logger") as logger:
                hash_staged_source_files(entries)

        logger.info.assert_called_once_with("Hashed staged source files: count=%s", 1)
        self.assertNotIn(file_contents.decode("utf-8"), str(logger.method_calls))
        self.assertNotIn(str(source_path), str(logger.method_calls))

    def test_missing_file_logs_error_and_reraises_without_raw_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            missing_path = Path(temp_directory) / "missing.txt"
            entries = (make_entry("entry-1", missing_path, "txt"),)

            with patch("app.ingestion.staging.source_hash_preflight.logger") as logger:
                with self.assertRaises(OSError):
                    hash_staged_source_files(entries)

        logger.error.assert_called_once_with(
            "Failed to hash staged source file: "
            "staging_entry_id=%s source_type=%s error_type=%s",
            "entry-1",
            "txt",
            "FileNotFoundError",
        )
        logger.info.assert_not_called()
        self.assertNotIn(str(missing_path), str(logger.method_calls))

    def test_unreadable_file_logs_error_and_reraises_without_raw_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            source_path = Path(temp_directory) / "source.txt"
            source_path.write_text("Source text.", encoding="utf-8")
            entries = (make_entry("entry-1", source_path, "txt"),)

            with (
                patch.object(Path, "open", side_effect=PermissionError("denied")),
                patch("app.ingestion.staging.source_hash_preflight.logger") as logger,
            ):
                with self.assertRaises(OSError):
                    hash_staged_source_files(entries)

        logger.error.assert_called_once_with(
            "Failed to hash staged source file: "
            "staging_entry_id=%s source_type=%s error_type=%s",
            "entry-1",
            "txt",
            "PermissionError",
        )
        logger.info.assert_not_called()
        self.assertNotIn(str(source_path), str(logger.method_calls))


def expected_sha256_hash(file_contents: bytes) -> str:
    return f"sha256:{hashlib.sha256(file_contents).hexdigest()}"


def make_entry(
    staging_entry_id: str,
    source_file_path: Path,
    source_file_type: str,
) -> TemporarySourceStagingEntry:
    return TemporarySourceStagingEntry(
        staging_entry_id=staging_entry_id,
        source_file_path=source_file_path,
        source_file_type=source_file_type,
        is_valid=True,
        error_message=None,
    )


if __name__ == "__main__":
    unittest.main()
