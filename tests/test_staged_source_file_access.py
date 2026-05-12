import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ingestion.staging.source_file_access import (
    StagedSourceFileAccessError,
    validate_staged_source_file_access,
)
from app.ingestion.staging.source_staging_state import TemporarySourceStagingEntry


class StagedSourceFileAccessTests(unittest.TestCase):
    def test_returns_entries_when_all_staged_files_exist_and_are_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            first_path = Path(temp_directory) / "first.txt"
            second_path = Path(temp_directory) / "second.pdf"
            first_path.write_text("First source.", encoding="utf-8")
            second_path.write_bytes(b"%PDF")
            entries = (
                make_entry("entry-1", first_path, "txt"),
                make_entry("entry-2", second_path, "pdf"),
            )

            validated_entries = validate_staged_source_file_access(entries)

        self.assertEqual(validated_entries, entries)

    def test_empty_batch_succeeds_without_creating_startup_policy(self) -> None:
        self.assertEqual(validate_staged_source_file_access([]), ())

    def test_missing_file_blocks_whole_batch_and_logs_warning_without_raw_path(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            existing_path = Path(temp_directory) / "existing.txt"
            missing_path = Path(temp_directory) / "missing.txt"
            existing_path.write_text("Existing source.", encoding="utf-8")
            entries = (
                make_entry("entry-1", existing_path, "txt"),
                make_entry("entry-2", missing_path, "txt"),
            )

            with patch("app.ingestion.staging.source_file_access.logger") as logger:
                with self.assertRaises(StagedSourceFileAccessError):
                    validate_staged_source_file_access(entries)

        logger.warning.assert_called_once_with(
            "Unavailable staged source files block ingestion: count=%s failures=%s",
            1,
            (("entry-2", "txt", "missing"),),
        )
        logger.error.assert_not_called()
        self.assertNotIn(str(existing_path), str(logger.method_calls))
        self.assertNotIn(str(missing_path), str(logger.method_calls))

    def test_directory_path_blocks_batch_as_unreadable_staged_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            source_directory = Path(temp_directory) / "source-directory"
            source_directory.mkdir()
            entries = (make_entry("entry-1", source_directory, "txt"),)

            with patch("app.ingestion.staging.source_file_access.logger") as logger:
                with self.assertRaises(StagedSourceFileAccessError):
                    validate_staged_source_file_access(entries)

        logger.warning.assert_called_once_with(
            "Unavailable staged source files block ingestion: count=%s failures=%s",
            1,
            (("entry-1", "txt", "not_file"),),
        )
        logger.error.assert_not_called()
        self.assertNotIn(str(source_directory), str(logger.method_calls))

    def test_open_denied_blocks_batch_and_logs_warning_without_raw_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            source_path = Path(temp_directory) / "source.txt"
            source_path.write_text("Source text.", encoding="utf-8")
            entries = (make_entry("entry-1", source_path, "txt"),)

            with (
                patch.object(Path, "open", side_effect=PermissionError("denied")),
                patch("app.ingestion.staging.source_file_access.logger") as logger,
            ):
                with self.assertRaises(StagedSourceFileAccessError):
                    validate_staged_source_file_access(entries)

        logger.warning.assert_called_once_with(
            "Unavailable staged source files block ingestion: count=%s failures=%s",
            1,
            (("entry-1", "txt", "unreadable"),),
        )
        logger.error.assert_not_called()
        self.assertNotIn(str(source_path), str(logger.method_calls))

    def test_expected_failures_are_collected_before_rejecting_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            missing_path = Path(temp_directory) / "missing.txt"
            source_directory = Path(temp_directory) / "source-directory"
            source_directory.mkdir()
            entries = (
                make_entry("entry-1", missing_path, "txt"),
                make_entry("entry-2", source_directory, "epub"),
            )

            with patch("app.ingestion.staging.source_file_access.logger") as logger:
                with self.assertRaises(StagedSourceFileAccessError):
                    validate_staged_source_file_access(entries)

        logger.warning.assert_called_once_with(
            "Unavailable staged source files block ingestion: count=%s failures=%s",
            2,
            (
                ("entry-1", "txt", "missing"),
                ("entry-2", "epub", "not_file"),
            ),
        )
        logger.error.assert_not_called()
        self.assertNotIn(str(missing_path), str(logger.method_calls))
        self.assertNotIn(str(source_directory), str(logger.method_calls))

    def test_unexpected_access_failure_logs_error_without_raw_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            source_path = Path(temp_directory) / "source.txt"
            source_path.write_text("Source text.", encoding="utf-8")
            entries = (make_entry("entry-1", source_path, "txt"),)

            with (
                patch.object(Path, "open", side_effect=RuntimeError("open failed")),
                patch("app.ingestion.staging.source_file_access.logger") as logger,
            ):
                with self.assertRaises(RuntimeError):
                    validate_staged_source_file_access(entries)

        logger.error.assert_called_once_with(
            "Unexpected staged source file access failure: "
            "staging_entry_id=%s source_type=%s error_type=%s",
            "entry-1",
            "txt",
            "RuntimeError",
        )
        logger.warning.assert_not_called()
        self.assertNotIn(str(source_path), str(logger.method_calls))


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
