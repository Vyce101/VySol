import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ingestion.commit_cleanup import (
    CommitFileCopy,
    CommitFilePreparationError,
    PreparedCommitFile,
    cleanup_commit_files,
    run_commit_with_rollback,
)


class CommitRollbackCleanupTests(unittest.TestCase):
    def test_copies_files_writes_records_promotes_files_and_commits(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            paths = make_commit_paths(temp_directory)
            write_source_file(paths.source_path)
            connection = make_connection()

            result = run_commit_with_rollback(
                connection,
                [CommitFileCopy(paths.source_path, paths.destination_path)],
                lambda active_connection: insert_source_record(
                    active_connection,
                    "source-1",
                ),
            )

            self.assertEqual(result, "source-1")
            self.assertEqual(
                paths.destination_path.read_text(encoding="utf-8"),
                "source",
            )
            self.assertEqual(list_source_ids(connection), ["source-1"])
            self.assertEqual(list(paths.destination_path.parent.glob("*.tmp")), [])
            connection.close()

    def test_copy_failure_skips_database_writes_and_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            paths = make_commit_paths(temp_directory)
            connection = make_connection()
            was_callback_called = False

            def write_records(active_connection: sqlite3.Connection) -> None:
                nonlocal was_callback_called
                was_callback_called = True
                insert_source_record(active_connection, "source-1")

            with self.assertRaises(FileNotFoundError):
                run_commit_with_rollback(
                    connection,
                    [CommitFileCopy(paths.source_path, paths.destination_path)],
                    write_records,
                )

            self.assertFalse(was_callback_called)
            self.assertFalse(paths.destination_path.exists())
            self.assertEqual(list_source_ids(connection), [])
            connection.close()

    def test_database_write_failure_rolls_back_and_removes_temporary_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            paths = make_commit_paths(temp_directory)
            write_source_file(paths.source_path)
            connection = make_connection()

            with patch("app.ingestion.commit_cleanup.logger") as logger:
                with self.assertRaises(sqlite3.Error):
                    run_commit_with_rollback(
                        connection,
                        [CommitFileCopy(paths.source_path, paths.destination_path)],
                        lambda active_connection: insert_source_record(
                            active_connection,
                            "",
                        ),
                    )

            self.assertFalse(paths.destination_path.exists())
            self.assertEqual(list(paths.destination_path.parent.glob("*.tmp")), [])
            self.assertEqual(list_source_ids(connection), [])
            self.assertGreaterEqual(logger.warning.call_count, 2)
            connection.close()

    def test_final_promotion_failure_rolls_back_records_and_cleans_temp_files(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            paths = make_commit_paths(temp_directory)
            write_source_file(paths.source_path)
            connection = make_connection()

            with patch(
                "app.ingestion.commit_cleanup.promote_prepared_commit_files",
                side_effect=OSError("promotion failed"),
            ):
                with self.assertRaises(OSError):
                    run_commit_with_rollback(
                        connection,
                        [CommitFileCopy(paths.source_path, paths.destination_path)],
                        lambda active_connection: insert_source_record(
                            active_connection,
                            "source-1",
                        ),
                    )

            self.assertFalse(paths.destination_path.exists())
            self.assertEqual(list(paths.destination_path.parent.glob("*.tmp")), [])
            self.assertEqual(list_source_ids(connection), [])
            connection.close()

    def test_commit_failure_removes_promoted_files_and_preserves_no_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            paths = make_commit_paths(temp_directory)
            write_source_file(paths.source_path)
            connection = FailingCommitConnection(make_connection())

            with self.assertRaises(sqlite3.Error):
                run_commit_with_rollback(
                    connection,
                    [CommitFileCopy(paths.source_path, paths.destination_path)],
                    lambda active_connection: insert_source_record(
                        active_connection,
                        "source-1",
                    ),
                )

            self.assertFalse(paths.destination_path.exists())
            self.assertEqual(list_source_ids(connection.connection), [])
            connection.close()

    def test_cleanup_can_be_retried_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temporary_path = Path(temp_directory) / "temporary-copy.tmp"
            destination_path = Path(temp_directory) / "final-copy.txt"
            temporary_path.write_text("temp", encoding="utf-8")
            destination_path.write_text("final", encoding="utf-8")
            prepared_file = PreparedCommitFile(temporary_path, destination_path)

            cleanup_commit_files([prepared_file], [prepared_file])
            cleanup_commit_files([prepared_file], [prepared_file])

            self.assertFalse(temporary_path.exists())
            self.assertFalse(destination_path.exists())

    def test_cleanup_failure_logs_error_and_critical_inconsistency(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temporary_path = Path(temp_directory) / "temporary-copy.tmp"
            temporary_path.write_text("temp", encoding="utf-8")
            prepared_file = PreparedCommitFile(
                temporary_path,
                Path(temp_directory) / "final-copy.txt",
            )

            with (
                patch("pathlib.Path.unlink", side_effect=OSError("cleanup failed")),
                patch("app.ingestion.commit_cleanup.logger") as logger,
            ):
                cleanup_commit_files([prepared_file], [])

            logger.error.assert_called_once()
            self.assertNotIn(temp_directory, repr(logger.method_calls))
            logger.critical.assert_called_once_with(
                "Unrecoverable commit cleanup inconsistency: remaining_file_count=%s",
                1,
            )

    def test_rollback_logs_without_raw_local_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            paths = make_commit_paths(temp_directory)
            write_source_file(paths.source_path)
            connection = make_connection()

            with patch("app.ingestion.commit_cleanup.logger") as logger:
                with self.assertRaises(sqlite3.Error):
                    run_commit_with_rollback(
                        connection,
                        [CommitFileCopy(paths.source_path, paths.destination_path)],
                        lambda active_connection: insert_source_record(
                            active_connection,
                            "",
                        ),
                    )

            log_output = repr(logger.method_calls)
            self.assertIn("Commit rollback started", log_output)
            self.assertIn("Commit rollback completed", log_output)
            self.assertNotIn(temp_directory, log_output)
            self.assertNotIn(paths.source_path.name, log_output)
            self.assertNotIn(paths.destination_path.name, log_output)
            connection.close()

    def test_rejects_duplicate_destinations_before_copying(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            paths = make_commit_paths(temp_directory)
            write_source_file(paths.source_path)
            connection = make_connection()

            with self.assertRaises(CommitFilePreparationError):
                run_commit_with_rollback(
                    connection,
                    [
                        CommitFileCopy(paths.source_path, paths.destination_path),
                        CommitFileCopy(paths.source_path, paths.destination_path),
                    ],
                    lambda active_connection: insert_source_record(
                        active_connection,
                        "source-1",
                    ),
                )

            self.assertFalse(paths.destination_path.exists())
            self.assertEqual(list_source_ids(connection), [])
            connection.close()

    def test_rejects_existing_destination_before_copying(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            paths = make_commit_paths(temp_directory)
            write_source_file(paths.source_path)
            paths.destination_path.parent.mkdir(parents=True)
            paths.destination_path.write_text("existing", encoding="utf-8")
            connection = make_connection()

            with self.assertRaises(CommitFilePreparationError):
                run_commit_with_rollback(
                    connection,
                    [CommitFileCopy(paths.source_path, paths.destination_path)],
                    lambda active_connection: insert_source_record(
                        active_connection,
                        "source-1",
                    ),
                )

            self.assertEqual(
                paths.destination_path.read_text(encoding="utf-8"),
                "existing",
            )
            self.assertEqual(list_source_ids(connection), [])
            connection.close()


class CommitPaths:
    def __init__(self, source_path: Path, destination_path: Path) -> None:
        self.source_path = source_path
        self.destination_path = destination_path


class FailingCommitConnection:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def execute(self, statement: str, parameters=()):
        return self.connection.execute(statement, parameters)

    def commit(self) -> None:
        raise sqlite3.Error("commit failed")

    def rollback(self) -> None:
        self.connection.rollback()

    def close(self) -> None:
        self.connection.close()


def make_commit_paths(temp_directory: str) -> CommitPaths:
    root = Path(temp_directory)
    return CommitPaths(
        source_path=root / "private-source.txt",
        destination_path=root / "world" / "sources" / "source-1.txt",
    )


def write_source_file(source_path: Path) -> None:
    source_path.write_text("source", encoding="utf-8")


def make_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE committed_sources (
            source_id TEXT PRIMARY KEY CHECK (length(trim(source_id)) > 0)
        )
        """
    )
    return connection


def insert_source_record(connection: sqlite3.Connection, source_id: str) -> str:
    connection.execute(
        "INSERT INTO committed_sources (source_id) VALUES (?)",
        (source_id,),
    )
    return source_id


def list_source_ids(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        """
        SELECT source_id
        FROM committed_sources
        ORDER BY source_id
        """
    ).fetchall()
    return [row[0] for row in rows]


if __name__ == "__main__":
    unittest.main()
