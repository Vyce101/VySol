from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from app.draft_worlds.splitter_settings import SplitterSettings
from app.ingestion.attempt_workspace import TemporaryIngestionWorkspace
from app.ingestion.new_world_commit import (
    NewWorldBatchCommitResult,
    NewWorldBatchValidationError,
    commit_new_world_batch,
)
from app.ingestion.parsed_source_outputs import TemporaryParsedSourceOutput
from app.ingestion.split_chunk_outputs import prepare_split_chunk_outputs
from app.ingestion.staging.source_hash_preflight import HashedStagedSource
from app.ingestion.staging.source_staging_state import TemporarySourceStagingEntry
from app.storage.chunks import list_chunks
from app.storage.committed_sources import list_committed_sources
from app.storage.database import bootstrap_global_database, close_global_connection
from app.storage.world_databases import open_world_database
from app.storage.world_folders import resolve_world_directory
from app.storage.world_splitter_settings import get_world_splitter_settings
from app.storage.worlds import (
    NewCommittedWorld,
    create_committed_world,
    list_committed_worlds,
)

WORLD_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
FIRST_SOURCE_ID = "11111111-1111-4111-8111-111111111111"
SECOND_SOURCE_ID = "22222222-2222-4222-8222-222222222222"
FIRST_CHUNK_ID = "33333333-3333-4333-8333-333333333333"
SECOND_CHUNK_ID = "44444444-4444-4444-8444-444444444444"
THIRD_CHUNK_ID = "55555555-5555-4555-8555-555555555555"
FOURTH_CHUNK_ID = "66666666-6666-4666-8666-666666666666"


class NewWorldCommitTests(unittest.TestCase):
    def tearDown(self) -> None:
        close_global_connection()

    def test_commits_new_world_after_world_data_source_copies_and_chunks_are_valid(
        self,
    ) -> None:
        with commit_environment() as environment:
            source_files = environment.write_source_files()
            workspace = environment.prepare_split_outputs()
            app_connection = environment.bootstrap_app_database()

            result = commit_with_fixed_ids(
                app_connection,
                workspace,
                make_hashed_sources(source_files),
            )

            world_directory = resolve_world_directory(result.committed_world.world_id)
            self.assertEqual(result.committed_world.world_id, WORLD_ID)
            self.assertEqual(
                [world.world_id for world in list_committed_worlds(app_connection)],
                [WORLD_ID],
            )
            self.assertTrue((world_directory / "world.sqlite").exists())
            self.assertTrue(
                (world_directory / "sources" / f"{FIRST_SOURCE_ID}.txt").exists()
            )
            self.assertTrue(
                (world_directory / "sources" / f"{SECOND_SOURCE_ID}.pdf").exists()
            )
            self.assertEqual(result.source_count, 2)
            self.assertEqual(result.chunk_count, 4)

            with close_after_test(open_world_database(WORLD_ID)) as world_connection:
                settings = get_world_splitter_settings(world_connection)
                sources = list_committed_sources(world_connection)
                chunks = list_chunks(world_connection)

            self.assertTrue(settings.is_locked)
            self.assertEqual([source.book_number for source in sources], [1, 2])
            self.assertEqual(
                [source.source_id for source in sources],
                [FIRST_SOURCE_ID, SECOND_SOURCE_ID],
            )
            self.assertEqual([chunk.book_number for chunk in chunks], [1, 1, 2, 2])
            self.assertEqual([chunk.chunk_number for chunk in chunks], [1, 2, 1, 2])

    def test_rejects_empty_batch_before_creating_world_or_app_index(self) -> None:
        with commit_environment() as environment:
            workspace = environment.make_workspace()
            app_connection = environment.bootstrap_app_database()

            with self.assertRaises(NewWorldBatchValidationError):
                commit_new_world_batch(
                    make_world_request(),
                    make_splitter_settings(),
                    workspace,
                    (),
                    app_connection,
                )

            self.assertFalse((environment.repo_root / "user" / "worlds").exists())
            self.assertEqual(list_committed_worlds(app_connection), [])

    def test_world_database_write_failure_cleans_world_folder_and_skips_app_index(
        self,
    ) -> None:
        with commit_environment() as environment:
            source_files = environment.write_source_files()
            workspace = environment.prepare_split_outputs()
            app_connection = environment.bootstrap_app_database()

            with (
                patch(
                    "app.ingestion.new_world_commit.insert_chunk_records",
                    side_effect=sqlite3.Error("chunk write failed"),
                ),
                patch("app.ingestion.new_world_commit.logger") as logger,
            ):
                with self.assertRaises(sqlite3.Error):
                    commit_with_fixed_ids(
                        app_connection,
                        workspace,
                        make_hashed_sources(source_files),
                    )

            self.assertFalse(resolve_world_directory(WORLD_ID).exists())
            self.assertEqual(list_committed_worlds(app_connection), [])
            logger.error.assert_called()
            logger.warning.assert_any_call(
                "New world batch cleanup started: world_id=%s",
                WORLD_ID,
            )

    def test_source_copy_failure_cleans_world_folder_and_skips_app_index(self) -> None:
        with commit_environment() as environment:
            source_files = environment.make_source_paths()
            workspace = environment.prepare_split_outputs()
            app_connection = environment.bootstrap_app_database()

            with patch("app.ingestion.new_world_commit.logger") as logger:
                with self.assertRaises(FileNotFoundError):
                    commit_with_fixed_ids(
                        app_connection,
                        workspace,
                        make_hashed_sources(source_files),
                    )

            self.assertFalse(resolve_world_directory(WORLD_ID).exists())
            self.assertEqual(list_committed_worlds(app_connection), [])
            self.assertNotIn(str(environment.repo_root), repr(logger.method_calls))

    def test_file_promotion_failure_cleans_world_folder_and_skips_app_index(
        self,
    ) -> None:
        with commit_environment() as environment:
            source_files = environment.write_source_files()
            workspace = environment.prepare_split_outputs()
            app_connection = environment.bootstrap_app_database()

            with patch(
                "app.ingestion.commit_cleanup.promote_prepared_commit_files",
                side_effect=OSError("promotion failed"),
            ):
                with self.assertRaises(OSError):
                    commit_with_fixed_ids(
                        app_connection,
                        workspace,
                        make_hashed_sources(source_files),
                    )

            self.assertFalse(resolve_world_directory(WORLD_ID).exists())
            self.assertEqual(list_committed_worlds(app_connection), [])

    def test_world_database_commit_failure_cleans_world_folder_and_skips_app_index(
        self,
    ) -> None:
        with commit_environment() as environment:
            source_files = environment.write_source_files()
            workspace = environment.prepare_split_outputs()
            app_connection = environment.bootstrap_app_database()

            with patch(
                "app.ingestion.new_world_commit.bootstrap_world_database",
                side_effect=bootstrap_failing_commit_world_database,
            ):
                with self.assertRaises(sqlite3.Error):
                    commit_with_fixed_ids(
                        app_connection,
                        workspace,
                        make_hashed_sources(source_files),
                    )

            self.assertFalse(resolve_world_directory(WORLD_ID).exists())
            self.assertEqual(list_committed_worlds(app_connection), [])

    def test_final_app_index_failure_cleans_valid_world_data_and_keeps_world_hidden(
        self,
    ) -> None:
        with commit_environment() as environment:
            source_files = environment.write_source_files()
            workspace = environment.prepare_split_outputs()
            app_connection = environment.bootstrap_app_database()
            existing_world = create_committed_world(make_world_request(), app_connection)

            with patch("app.ingestion.new_world_commit.logger") as logger:
                with self.assertRaises(ValueError):
                    commit_with_fixed_ids(
                        app_connection,
                        workspace,
                        make_hashed_sources(source_files),
                    )

            self.assertFalse(resolve_world_directory(WORLD_ID).exists())
            self.assertEqual(
                [world.world_id for world in list_committed_worlds(app_connection)],
                [existing_world.world_id],
            )
            logger.error.assert_called()
            logger.warning.assert_any_call(
                "New world batch cleanup completed: world_id=%s",
                WORLD_ID,
            )

    def test_cleanup_failure_after_app_index_failure_logs_critical(self) -> None:
        with commit_environment() as environment:
            source_files = environment.write_source_files()
            workspace = environment.prepare_split_outputs()
            app_connection = environment.bootstrap_app_database()
            create_committed_world(make_world_request(), app_connection)

            with (
                patch("app.ingestion.new_world_commit.shutil.rmtree", side_effect=OSError),
                patch("app.ingestion.new_world_commit.logger") as logger,
            ):
                with self.assertRaises(ValueError):
                    commit_with_fixed_ids(
                        app_connection,
                        workspace,
                        make_hashed_sources(source_files),
                    )

            logger.critical.assert_called_once_with(
                "Unrecoverable DB/file consistency failure during new world cleanup: "
                "world_id=%s",
                WORLD_ID,
            )

    def test_success_logs_summary_without_chunk_text_or_local_paths(self) -> None:
        sensitive_chunk_text = "NoLog"

        with commit_environment() as environment:
            source_files = environment.write_source_files()
            workspace = environment.prepare_split_outputs(sensitive_chunk_text)
            app_connection = environment.bootstrap_app_database()

            with patch("app.ingestion.new_world_commit.logger") as logger:
                commit_with_fixed_ids(
                    app_connection,
                    workspace,
                    make_hashed_sources(source_files),
                )

            log_output = repr(logger.method_calls)

        self.assertIn("Committed new world batch", log_output)
        self.assertNotIn(sensitive_chunk_text, log_output)
        self.assertNotIn(str(environment.repo_root), log_output)


class CommitEnvironment:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def bootstrap_app_database(self) -> sqlite3.Connection:
        return bootstrap_global_database(self.repo_root / "user" / "data" / "app.sqlite")

    def make_workspace(self) -> TemporaryIngestionWorkspace:
        workspace_path = self.repo_root / "user" / "data" / "workspace-test"
        workspace_path.mkdir(parents=True, exist_ok=True)
        return TemporaryIngestionWorkspace("attempt-1", workspace_path)

    def make_source_paths(self) -> tuple[Path, Path]:
        return (
            self.repo_root / "uploads" / "book-one.txt",
            self.repo_root / "uploads" / "book-two.pdf",
        )

    def write_source_files(self) -> tuple[Path, Path]:
        first_source, second_source = self.make_source_paths()
        first_source.parent.mkdir(parents=True, exist_ok=True)
        first_source.write_text("first source", encoding="utf-8")
        second_source.write_text("second source", encoding="utf-8")
        return first_source, second_source

    def prepare_split_outputs(
        self,
        first_text: str = "abcdefghij",
    ) -> TemporaryIngestionWorkspace:
        workspace = self.make_workspace()
        prepare_split_chunk_outputs(
            workspace,
            (
                TemporaryParsedSourceOutput("attempt-1", "entry-1", "txt", first_text),
                TemporaryParsedSourceOutput("attempt-1", "entry-2", "pdf", "klmnop"),
            ),
            make_splitter_settings(),
        )
        return workspace


@contextmanager
def commit_environment() -> Iterator[CommitEnvironment]:
    with tempfile.TemporaryDirectory() as temp_directory:
        repo_root = Path(temp_directory) / "repo"

        with patch("app.storage.paths.REPO_ROOT", repo_root):
            try:
                yield CommitEnvironment(repo_root)
            finally:
                close_global_connection()


def commit_with_fixed_ids(
    app_connection: sqlite3.Connection,
    workspace: TemporaryIngestionWorkspace,
    hashed_sources: tuple[HashedStagedSource, ...],
) -> NewWorldBatchCommitResult:
    with (
        patch(
            "app.ingestion.new_world_commit.uuid4",
            side_effect=(
                UUID(WORLD_ID),
                UUID(FIRST_CHUNK_ID),
                UUID(SECOND_CHUNK_ID),
                UUID(THIRD_CHUNK_ID),
                UUID(FOURTH_CHUNK_ID),
            ),
        ),
        patch(
            "app.storage.committed_source_files.uuid4",
            side_effect=(UUID(FIRST_SOURCE_ID), UUID(SECOND_SOURCE_ID)),
        ),
    ):
        return commit_new_world_batch(
            make_world_request(),
            make_splitter_settings(),
            workspace,
            hashed_sources,
            app_connection,
        )


def make_world_request() -> NewCommittedWorld:
    return NewCommittedWorld(
        display_name="Atomic World",
        description="Committed after first batch",
        background_asset_id="builtin-image-main-world",
        font_asset_id="builtin-font-inter",
    )


def make_splitter_settings() -> SplitterSettings:
    return SplitterSettings(
        chunk_size=5,
        max_lookback_size=0,
        overlap_size=2,
        splitter_version="ignored-caller-version",
    )


def make_hashed_sources(source_files: tuple[Path, Path]) -> tuple[HashedStagedSource, ...]:
    return (
        make_hashed_source("entry-1", source_files[0], "txt", "sha256:first"),
        make_hashed_source("entry-2", source_files[1], "pdf", "sha256:second"),
    )


def make_hashed_source(
    staging_entry_id: str,
    source_file_path: Path,
    source_file_type: str,
    source_hash: str,
) -> HashedStagedSource:
    return HashedStagedSource(
        staged_source=TemporarySourceStagingEntry(
            staging_entry_id=staging_entry_id,
            source_file_path=source_file_path,
            source_file_type=source_file_type,
            is_valid=True,
            error_message=None,
        ),
        source_hash=source_hash,
    )


def bootstrap_failing_commit_world_database(world_id: str) -> "FailingCommitConnection":
    return FailingCommitConnection(open_world_database(world_id))


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


@contextmanager
def close_after_test(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield connection
    finally:
        connection.close()


if __name__ == "__main__":
    unittest.main()
