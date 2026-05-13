from collections.abc import Iterator, Sequence
from contextlib import contextmanager
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from app.ingestion.commit_cleanup import CommitFilePreparationError
from app.ingestion.staging.source_hash_preflight import HashedStagedSource
from app.ingestion.staging.source_staging_state import TemporarySourceStagingEntry
from app.storage.committed_source_files import (
    PreparedCommittedSourceFile,
    prepare_committed_source_files,
    run_committed_source_file_commit_with_rollback,
)

WORLD_ID = "3f7f88fa-c2f3-4b67-bec6-4f2dfc77e8f4"
FIRST_SOURCE_ID = "11111111-1111-4111-8111-111111111111"


class CommittedSourceFileStorageTests(unittest.TestCase):
    def test_prepares_safe_internal_filename_and_preserves_original_filename(
        self,
    ) -> None:
        with patched_world_storage() as storage:
            source_file = storage.repo_root / "uploads" / "Volume One.TXT"
            write_source_file(source_file, "first source")
            hashed_source = make_hashed_source(source_file, "txt", "sha256:first")

            with patch(
                "app.storage.committed_source_files.uuid4",
                return_value=UUID(FIRST_SOURCE_ID),
            ):
                prepared_sources = prepare_committed_source_files(
                    WORLD_ID,
                    (hashed_source,),
                )

            prepared_source = prepared_sources[0]
            expected_destination = (
                storage.sources_directory / f"{FIRST_SOURCE_ID}.txt"
            )

            self.assertEqual(prepared_source.source_id, FIRST_SOURCE_ID)
            self.assertEqual(prepared_source.staging_entry_id, "Volume One")
            self.assertEqual(prepared_source.original_filename, "Volume One.TXT")
            self.assertEqual(
                prepared_source.stored_path,
                f"sources/{FIRST_SOURCE_ID}.txt",
            )
            self.assertEqual(prepared_source.source_file_type, "txt")
            self.assertEqual(prepared_source.source_hash, "sha256:first")
            self.assertEqual(prepared_source.file_copy.source_path, source_file)
            self.assertEqual(
                prepared_source.file_copy.destination_path,
                expected_destination,
            )
            self.assertFalse(expected_destination.exists())

    def test_prepare_logs_safe_summary_without_raw_paths_or_filenames(self) -> None:
        with patched_world_storage() as storage:
            source_file = storage.repo_root / "uploads" / "Secret Volume.pdf"
            write_source_file(source_file, "secret")

            with (
                patch(
                    "app.storage.committed_source_files.uuid4",
                    return_value=UUID(FIRST_SOURCE_ID),
                ),
                patch("app.storage.committed_source_files.logger") as logger,
            ):
                prepare_committed_source_files(
                    WORLD_ID,
                    (make_hashed_source(source_file, "pdf", "sha256:secret"),),
                )

            log_output = repr(logger.method_calls)
            self.assertIn("Prepared committed source file copies", log_output)
            self.assertIn(FIRST_SOURCE_ID, log_output)
            self.assertNotIn(str(source_file), log_output)
            self.assertNotIn(source_file.name, log_output)

    def test_unsafe_suffix_is_ignored_and_logged_without_original_filename(
        self,
    ) -> None:
        with patched_world_storage() as storage:
            source_file = storage.repo_root / "uploads" / "notes.not-safe"
            write_source_file(source_file, "notes")

            with (
                patch(
                    "app.storage.committed_source_files.uuid4",
                    return_value=UUID(FIRST_SOURCE_ID),
                ),
                patch("app.storage.committed_source_files.logger") as logger,
            ):
                prepared_sources = prepare_committed_source_files(
                    WORLD_ID,
                    (make_hashed_source(source_file, "txt", "sha256:notes"),),
                )

            prepared_source = prepared_sources[0]
            self.assertEqual(prepared_source.stored_path, f"sources/{FIRST_SOURCE_ID}")
            self.assertEqual(
                prepared_source.file_copy.destination_path,
                storage.sources_directory / FIRST_SOURCE_ID,
            )
            logger.warning.assert_called_once_with(
                "Unsupported committed source filename suffix ignored."
            )
            self.assertNotIn(source_file.name, repr(logger.method_calls))

    def test_run_commit_copies_files_writes_records_and_returns_callback_result(
        self,
    ) -> None:
        with patched_world_storage() as storage:
            source_file = storage.repo_root / "uploads" / "accepted.epub"
            write_source_file(source_file, "accepted source")
            prepared_sources = prepare_sources_with_ids(
                (source_file,),
                (FIRST_SOURCE_ID,),
            )
            connection = make_connection()

            result = run_committed_source_file_commit_with_rollback(
                connection,
                prepared_sources,
                insert_source_records,
            )

            stored_file = storage.sources_directory / f"{FIRST_SOURCE_ID}.epub"
            self.assertEqual(result, (FIRST_SOURCE_ID,))
            self.assertEqual(stored_file.read_text(encoding="utf-8"), "accepted source")
            self.assertEqual(
                list_source_rows(connection),
                [(FIRST_SOURCE_ID, "accepted.epub", f"sources/{FIRST_SOURCE_ID}.epub")],
            )
            self.assertEqual(list(storage.sources_directory.glob("*.tmp")), [])
            connection.close()

    def test_copy_failure_aborts_commit_and_skips_database_callback(self) -> None:
        with patched_world_storage() as storage:
            missing_file = storage.repo_root / "uploads" / "missing.pdf"
            prepared_sources = prepare_sources_with_ids(
                (missing_file,),
                (FIRST_SOURCE_ID,),
            )
            connection = make_connection()
            was_callback_called = False

            def write_records(
                active_connection: sqlite3.Connection,
                source_files: tuple[PreparedCommittedSourceFile, ...],
            ) -> tuple[str, ...]:
                nonlocal was_callback_called
                was_callback_called = True
                return insert_source_records(active_connection, source_files)

            with patch("app.storage.committed_source_files.logger") as logger:
                with self.assertRaises(FileNotFoundError):
                    run_committed_source_file_commit_with_rollback(
                        connection,
                        prepared_sources,
                        write_records,
                    )

            self.assertFalse(was_callback_called)
            self.assertFalse(
                (storage.sources_directory / f"{FIRST_SOURCE_ID}.pdf").exists()
            )
            self.assertEqual(list_source_rows(connection), [])
            self.assertEqual(list(storage.sources_directory.glob("*.tmp")), [])
            logger.error.assert_called_once()
            log_output = repr(logger.method_calls)
            self.assertIn(FIRST_SOURCE_ID, log_output)
            self.assertNotIn(str(missing_file), log_output)
            self.assertNotIn(missing_file.name, log_output)
            connection.close()

    def test_database_failure_rolls_back_records_and_removes_temporary_copy(
        self,
    ) -> None:
        with patched_world_storage() as storage:
            source_file = storage.repo_root / "uploads" / "accepted.txt"
            write_source_file(source_file, "accepted source")
            prepared_sources = prepare_sources_with_ids(
                (source_file,),
                (FIRST_SOURCE_ID,),
            )
            connection = make_connection()

            def fail_write(
                active_connection: sqlite3.Connection,
                source_files: tuple[PreparedCommittedSourceFile, ...],
            ) -> None:
                active_connection.execute(
                    "INSERT INTO committed_source_files (source_id) VALUES (?)",
                    ("",),
                )

            with self.assertRaises(sqlite3.Error):
                run_committed_source_file_commit_with_rollback(
                    connection,
                    prepared_sources,
                    fail_write,
                )

            self.assertFalse(
                (storage.sources_directory / f"{FIRST_SOURCE_ID}.txt").exists()
            )
            self.assertEqual(list_source_rows(connection), [])
            self.assertEqual(list(storage.sources_directory.glob("*.tmp")), [])
            connection.close()

    def test_commit_failure_removes_promoted_files_and_preserves_no_records(
        self,
    ) -> None:
        with patched_world_storage() as storage:
            source_file = storage.repo_root / "uploads" / "accepted.txt"
            write_source_file(source_file, "accepted source")
            prepared_sources = prepare_sources_with_ids(
                (source_file,),
                (FIRST_SOURCE_ID,),
            )
            connection = FailingCommitConnection(make_connection())

            with self.assertRaises(sqlite3.Error):
                run_committed_source_file_commit_with_rollback(
                    connection,
                    prepared_sources,
                    insert_source_records,
                )

            self.assertFalse(
                (storage.sources_directory / f"{FIRST_SOURCE_ID}.txt").exists()
            )
            self.assertEqual(list_source_rows(connection.connection), [])
            connection.close()

    def test_duplicate_destination_rejects_before_copying_or_database_writes(
        self,
    ) -> None:
        with patched_world_storage() as storage:
            first_source = storage.repo_root / "uploads" / "first.txt"
            second_source = storage.repo_root / "uploads" / "second.txt"
            write_source_file(first_source, "first")
            write_source_file(second_source, "second")
            prepared_sources = prepare_sources_with_ids(
                (first_source, second_source),
                (FIRST_SOURCE_ID, FIRST_SOURCE_ID),
            )
            connection = make_connection()
            was_callback_called = False

            def write_records(
                active_connection: sqlite3.Connection,
                source_files: tuple[PreparedCommittedSourceFile, ...],
            ) -> tuple[str, ...]:
                nonlocal was_callback_called
                was_callback_called = True
                return insert_source_records(active_connection, source_files)

            with self.assertRaises(CommitFilePreparationError):
                run_committed_source_file_commit_with_rollback(
                    connection,
                    prepared_sources,
                    write_records,
                )

            self.assertFalse(was_callback_called)
            self.assertFalse(
                (storage.sources_directory / f"{FIRST_SOURCE_ID}.txt").exists()
            )
            self.assertEqual(list_source_rows(connection), [])
            connection.close()

    def test_existing_destination_rejects_before_copying_or_database_writes(
        self,
    ) -> None:
        with patched_world_storage() as storage:
            source_file = storage.repo_root / "uploads" / "accepted.txt"
            write_source_file(source_file, "accepted")
            prepared_sources = prepare_sources_with_ids(
                (source_file,),
                (FIRST_SOURCE_ID,),
            )
            existing_destination = storage.sources_directory / f"{FIRST_SOURCE_ID}.txt"
            existing_destination.parent.mkdir(parents=True)
            existing_destination.write_text("existing", encoding="utf-8")
            connection = make_connection()
            was_callback_called = False

            def write_records(
                active_connection: sqlite3.Connection,
                source_files: tuple[PreparedCommittedSourceFile, ...],
            ) -> tuple[str, ...]:
                nonlocal was_callback_called
                was_callback_called = True
                return insert_source_records(active_connection, source_files)

            with self.assertRaises(CommitFilePreparationError):
                run_committed_source_file_commit_with_rollback(
                    connection,
                    prepared_sources,
                    write_records,
                )

            self.assertFalse(was_callback_called)
            self.assertEqual(existing_destination.read_text(encoding="utf-8"), "existing")
            self.assertEqual(list_source_rows(connection), [])
            connection.close()


@contextmanager
def patched_world_storage() -> Iterator["PatchedWorldStorage"]:
    with tempfile.TemporaryDirectory() as temp_directory:
        repo_root = Path(temp_directory) / "repo"
        sources_directory = repo_root / "user" / "worlds" / WORLD_ID / "sources"
        storage = PatchedWorldStorage(repo_root, sources_directory)

        with patch("app.storage.paths.REPO_ROOT", repo_root):
            yield storage


def prepare_sources_with_ids(
    source_files: Sequence[Path],
    source_ids: Sequence[str],
) -> tuple[PreparedCommittedSourceFile, ...]:
    hashed_sources = tuple(
        make_hashed_source(
            source_file,
            source_file.suffix.removeprefix(".") or "txt",
            f"sha256:{index}",
        )
        for index, source_file in enumerate(source_files)
    )
    uuid_values = [UUID(source_id) for source_id in source_ids]

    with patch(
        "app.storage.committed_source_files.uuid4",
        side_effect=uuid_values,
    ):
        return prepare_committed_source_files(WORLD_ID, hashed_sources)


def make_hashed_source(
    source_file_path: Path,
    source_file_type: str,
    source_hash: str,
) -> HashedStagedSource:
    return HashedStagedSource(
        staged_source=TemporarySourceStagingEntry(
            staging_entry_id=source_file_path.stem,
            source_file_path=source_file_path,
            source_file_type=source_file_type,
            is_valid=True,
            error_message=None,
        ),
        source_hash=source_hash,
    )


def write_source_file(source_file: Path, contents: str) -> None:
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text(contents, encoding="utf-8")


def make_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE committed_source_files (
            source_id TEXT PRIMARY KEY CHECK (length(trim(source_id)) > 0),
            original_filename TEXT,
            stored_path TEXT
        )
        """
    )
    return connection


def insert_source_records(
    connection: sqlite3.Connection,
    source_files: tuple[PreparedCommittedSourceFile, ...],
) -> tuple[str, ...]:
    connection.executemany(
        """
        INSERT INTO committed_source_files (
            source_id,
            original_filename,
            stored_path
        )
        VALUES (?, ?, ?)
        """,
        [
            (source.source_id, source.original_filename, source.stored_path)
            for source in source_files
        ],
    )
    return tuple(source.source_id for source in source_files)


def list_source_rows(connection: sqlite3.Connection) -> list[tuple[str, str, str]]:
    rows = connection.execute(
        """
        SELECT source_id, original_filename, stored_path
        FROM committed_source_files
        ORDER BY source_id
        """
    ).fetchall()
    return [(row[0], row[1], row[2]) for row in rows]


class FailingCommitConnection:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def execute(self, statement: str, parameters=()):
        return self.connection.execute(statement, parameters)

    def executemany(self, statement: str, parameters):
        return self.connection.executemany(statement, parameters)

    def commit(self) -> None:
        raise sqlite3.Error("commit failed")

    def rollback(self) -> None:
        self.connection.rollback()

    def close(self) -> None:
        self.connection.close()


class PatchedWorldStorage:
    def __init__(self, repo_root: Path, sources_directory: Path) -> None:
        self.repo_root = repo_root
        self.sources_directory = sources_directory


if __name__ == "__main__":
    unittest.main()
