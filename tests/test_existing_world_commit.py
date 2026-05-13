from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from app.draft_worlds.splitter_settings import SplitterSettings
from app.ingestion.attempt_cancellation import (
    clear_attempt_cancellation,
    request_attempt_cancellation,
)
from app.ingestion.existing_world_commit import (
    ExistingWorldBatchCommitResult,
    ExistingWorldBatchValidationError,
    commit_existing_world_batch,
)
from app.ingestion.parsed_source_outputs import TemporaryParsedSourceOutput
from app.ingestion.split_chunk_outputs import prepare_split_chunk_outputs
from app.ingestion.staging.source_hash_preflight import HashedStagedSource
from app.ingestion.staging.source_staging_state import TemporarySourceStagingEntry
from app.storage.chunks import NewChunk, append_chunks, list_chunks
from app.storage.committed_sources import (
    NewCommittedSource,
    append_committed_source,
    list_committed_sources,
)
from app.storage.database import bootstrap_global_database, close_global_connection
from app.storage.world_databases import open_world_database
from app.storage.world_folders import resolve_world_directory
from app.storage.worlds import (
    NewCommittedWorld,
    create_committed_world,
    get_committed_world,
)

WORLD_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
EXISTING_SOURCE_ID = "00000000-0000-4000-8000-000000000001"
FIRST_NEW_SOURCE_ID = "11111111-1111-4111-8111-111111111111"
SECOND_NEW_SOURCE_ID = "22222222-2222-4222-8222-222222222222"
FIRST_NEW_CHUNK_ID = "33333333-3333-4333-8333-333333333333"
SECOND_NEW_CHUNK_ID = "44444444-4444-4444-8444-444444444444"
THIRD_NEW_CHUNK_ID = "55555555-5555-4555-8555-555555555555"
FOURTH_NEW_CHUNK_ID = "66666666-6666-4666-8666-666666666666"
FIFTH_NEW_CHUNK_ID = "77777777-7777-4777-8777-777777777777"
SIXTH_NEW_CHUNK_ID = "88888888-8888-4888-8888-888888888888"


class ExistingWorldCommitTests(unittest.TestCase):
    def tearDown(self) -> None:
        close_global_connection()

    def test_appends_sources_chunks_and_refreshes_last_used_at(self) -> None:
        with commit_environment() as environment:
            source_files = environment.write_source_files()
            workspace = environment.prepare_split_outputs()
            app_connection = environment.bootstrap_app_database()

            with patch(
                "app.storage.worlds.get_last_used_at_timestamp",
                side_effect=("2026-01-01 00:00:00", "2026-01-02 00:00:00"),
            ):
                environment.bootstrap_existing_world(app_connection)
                result = commit_with_fixed_ids(
                    app_connection,
                    workspace,
                    make_hashed_sources(source_files),
                )

            world_directory = resolve_world_directory(WORLD_ID)
            self.assertEqual(result.source_count, 2)
            self.assertEqual(result.chunk_count, 4)
            self.assertTrue(result.last_used_at_refreshed)
            self.assertTrue((world_directory / "sources" / "existing.txt").exists())
            self.assertTrue(
                (world_directory / "sources" / f"{FIRST_NEW_SOURCE_ID}.txt").exists()
            )
            self.assertTrue(
                (world_directory / "sources" / f"{SECOND_NEW_SOURCE_ID}.pdf").exists()
            )
            self.assertEqual(
                get_committed_world(WORLD_ID, app_connection).last_used_at,
                "2026-01-02 00:00:00",
            )

            with close_after_test(open_world_database(WORLD_ID)) as world_connection:
                sources = list_committed_sources(world_connection)
                chunks = list_chunks(world_connection)

            self.assertEqual(
                [source.source_id for source in sources],
                [EXISTING_SOURCE_ID, FIRST_NEW_SOURCE_ID, SECOND_NEW_SOURCE_ID],
            )
            self.assertEqual([source.book_number for source in sources], [1, 2, 3])
            self.assertEqual(
                [chunk.book_number for chunk in chunks],
                [1, 2, 2, 3, 3],
            )
            self.assertEqual(
                [chunk.chunk_number for chunk in chunks],
                [1, 1, 2, 1, 2],
            )

    def test_last_used_at_failure_is_non_fatal_after_successful_world_commit(
        self,
    ) -> None:
        with commit_environment() as environment:
            source_files = environment.write_source_files()
            workspace = environment.prepare_split_outputs()
            app_connection = environment.bootstrap_app_database()
            environment.bootstrap_existing_world(app_connection)

            with (
                patch(
                    "app.ingestion.existing_world_commit.mark_committed_world_used",
                    side_effect=sqlite3.Error("timestamp failed"),
                ),
                patch("app.ingestion.existing_world_commit.logger") as logger,
            ):
                result = commit_with_fixed_ids(
                    app_connection,
                    workspace,
                    make_hashed_sources(source_files),
                )

            self.assertFalse(result.last_used_at_refreshed)
            logger.error.assert_any_call(
                "Failed to refresh existing world last_used_at after source commit: "
                "error_type=%s",
                "Error",
            )
            with close_after_test(open_world_database(WORLD_ID)) as world_connection:
                self.assertEqual(
                    [source.source_id for source in list_committed_sources(world_connection)],
                    [EXISTING_SOURCE_ID, FIRST_NEW_SOURCE_ID, SECOND_NEW_SOURCE_ID],
                )

    def test_missing_world_index_fails_before_world_storage_is_created(self) -> None:
        with commit_environment() as environment:
            source_files = environment.write_source_files()
            workspace = environment.prepare_split_outputs()
            app_connection = environment.bootstrap_app_database()

            with self.assertRaises(ExistingWorldBatchValidationError):
                commit_with_fixed_ids(
                    app_connection,
                    workspace,
                    make_hashed_sources(source_files),
                )

            self.assertFalse(resolve_world_directory(WORLD_ID).exists())

    def test_rejects_cancelled_attempt_before_mutating_existing_world(self) -> None:
        with commit_environment() as environment:
            source_files = environment.write_source_files()
            workspace = environment.prepare_split_outputs()
            app_connection = environment.bootstrap_app_database()
            environment.bootstrap_existing_world(app_connection)
            original_last_used_at = get_committed_world(
                WORLD_ID,
                app_connection,
            ).last_used_at
            request_attempt_cancellation(workspace.attempt_id)

            try:
                with self.assertRaises(ExistingWorldBatchValidationError):
                    commit_with_fixed_ids(
                        app_connection,
                        workspace,
                        make_hashed_sources(source_files),
                    )
            finally:
                clear_attempt_cancellation(workspace.attempt_id)

            environment.assert_existing_world_unchanged()
            self.assertEqual(
                get_committed_world(WORLD_ID, app_connection).last_used_at,
                original_last_used_at,
            )

    def test_duplicate_existing_source_hash_leaves_world_unchanged(self) -> None:
        with commit_environment() as environment:
            source_files = environment.write_source_files()
            workspace = environment.prepare_split_outputs()
            app_connection = environment.bootstrap_app_database()
            environment.bootstrap_existing_world(app_connection)

            with self.assertRaises(ValueError):
                commit_with_fixed_ids(
                    app_connection,
                    workspace,
                    make_hashed_sources(source_files, first_hash="sha256:existing"),
                )

            environment.assert_existing_world_unchanged()

    def test_source_copy_failure_leaves_world_unchanged(self) -> None:
        with commit_environment() as environment:
            source_files = environment.make_source_paths()
            workspace = environment.prepare_split_outputs("Never log this chunk text.")
            app_connection = environment.bootstrap_app_database()
            environment.bootstrap_existing_world(app_connection)

            with patch("app.ingestion.existing_world_commit.logger") as logger:
                with self.assertRaises(FileNotFoundError):
                    commit_with_fixed_ids(
                        app_connection,
                        workspace,
                        make_hashed_sources(source_files),
                    )

            environment.assert_existing_world_unchanged()
            log_output = repr(logger.method_calls)
            self.assertNotIn("Never log this chunk text.", log_output)
            self.assertNotIn(str(environment.repo_root), log_output)

    def test_database_write_failure_rolls_back_new_records_and_files(self) -> None:
        with commit_environment() as environment:
            source_files = environment.write_source_files()
            workspace = environment.prepare_split_outputs()
            app_connection = environment.bootstrap_app_database()
            environment.bootstrap_existing_world(app_connection)

            with patch(
                "app.ingestion.world_batch_records.insert_chunk_records",
                side_effect=sqlite3.Error("chunk write failed"),
            ):
                with self.assertRaises(sqlite3.Error):
                    commit_with_fixed_ids(
                        app_connection,
                        workspace,
                        make_hashed_sources(source_files),
                    )

            environment.assert_existing_world_unchanged()

    def test_file_promotion_failure_leaves_world_unchanged(self) -> None:
        with commit_environment() as environment:
            source_files = environment.write_source_files()
            workspace = environment.prepare_split_outputs()
            app_connection = environment.bootstrap_app_database()
            environment.bootstrap_existing_world(app_connection)

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

            environment.assert_existing_world_unchanged()

    def test_world_database_commit_failure_removes_promoted_new_files(self) -> None:
        with commit_environment() as environment:
            source_files = environment.write_source_files()
            workspace = environment.prepare_split_outputs()
            app_connection = environment.bootstrap_app_database()
            environment.bootstrap_existing_world(app_connection)

            with patch(
                "app.ingestion.existing_world_commit.open_world_database",
                side_effect=bootstrap_failing_commit_world_database,
            ):
                with self.assertRaises(sqlite3.Error):
                    commit_with_fixed_ids(
                        app_connection,
                        workspace,
                        make_hashed_sources(source_files),
                    )

            environment.assert_existing_world_unchanged()

    def test_success_logs_summary_without_chunk_text_or_local_paths(self) -> None:
        sensitive_chunk_text = "NoLogChunkText"

        with commit_environment() as environment:
            source_files = environment.write_source_files()
            workspace = environment.prepare_split_outputs(sensitive_chunk_text)
            app_connection = environment.bootstrap_app_database()
            environment.bootstrap_existing_world(app_connection)

            with patch("app.ingestion.existing_world_commit.logger") as logger:
                commit_with_fixed_ids(
                    app_connection,
                    workspace,
                    make_hashed_sources(source_files),
                )

            log_output = repr(logger.method_calls)

        self.assertIn("Committed existing world batch", log_output)
        self.assertNotIn(sensitive_chunk_text, log_output)
        self.assertNotIn(str(environment.repo_root), log_output)


class CommitEnvironment:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def bootstrap_app_database(self) -> sqlite3.Connection:
        return bootstrap_global_database(self.repo_root / "user" / "data" / "app.sqlite")

    def bootstrap_existing_world(self, app_connection: sqlite3.Connection) -> None:
        with patch("app.storage.worlds.uuid4", return_value=UUID(WORLD_ID)):
            create_committed_world(
                NewCommittedWorld(
                    display_name="Existing Atomic World",
                    description="Already committed",
                    background_asset_id="builtin-image-main-world",
                    font_asset_id="builtin-font-inter",
                ),
                app_connection,
            )

        with close_after_test(open_world_database(WORLD_ID)) as world_connection:
            append_committed_source(world_connection, make_existing_source())
            append_chunks(world_connection, [make_existing_chunk()])

        existing_file = resolve_world_directory(WORLD_ID) / "sources" / "existing.txt"
        existing_file.write_text("existing source", encoding="utf-8")

    def make_workspace(self) -> "TemporaryIngestionWorkspace":
        from app.ingestion.attempt_workspace import TemporaryIngestionWorkspace

        workspace_path = self.repo_root / "user" / "data" / "workspace-test"
        workspace_path.mkdir(parents=True, exist_ok=True)
        return TemporaryIngestionWorkspace("attempt-1", workspace_path)

    def make_source_paths(self) -> tuple[Path, Path]:
        return (
            self.repo_root / "uploads" / "book-two.txt",
            self.repo_root / "uploads" / "book-three.pdf",
        )

    def write_source_files(self) -> tuple[Path, Path]:
        first_source, second_source = self.make_source_paths()
        first_source.parent.mkdir(parents=True, exist_ok=True)
        first_source.write_text("first new source", encoding="utf-8")
        second_source.write_text("second new source", encoding="utf-8")
        return first_source, second_source

    def prepare_split_outputs(
        self,
        first_text: str = "abcdefghij",
    ) -> "TemporaryIngestionWorkspace":
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

    def assert_existing_world_unchanged(self) -> None:
        world_directory = resolve_world_directory(WORLD_ID)
        source_files = sorted(
            path.name for path in (world_directory / "sources").iterdir()
        )
        self_source_files = ["existing.txt"]

        with close_after_test(open_world_database(WORLD_ID)) as world_connection:
            sources = list_committed_sources(world_connection)
            chunks = list_chunks(world_connection)

        assert source_files == self_source_files
        assert [source.source_id for source in sources] == [EXISTING_SOURCE_ID]
        assert [chunk.chunk_id for chunk in chunks] == ["existing-chunk-1"]


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
    workspace,
    hashed_sources: tuple[HashedStagedSource, ...],
) -> ExistingWorldBatchCommitResult:
    with (
        patch(
            "app.storage.committed_source_files.uuid4",
            side_effect=(UUID(FIRST_NEW_SOURCE_ID), UUID(SECOND_NEW_SOURCE_ID)),
        ),
        patch(
            "app.ingestion.existing_world_commit.uuid4",
            side_effect=(
                UUID(FIRST_NEW_CHUNK_ID),
                UUID(SECOND_NEW_CHUNK_ID),
                UUID(THIRD_NEW_CHUNK_ID),
                UUID(FOURTH_NEW_CHUNK_ID),
                UUID(FIFTH_NEW_CHUNK_ID),
                UUID(SIXTH_NEW_CHUNK_ID),
            ),
        ),
    ):
        return commit_existing_world_batch(
            WORLD_ID,
            workspace,
            hashed_sources,
            app_connection,
        )


def make_existing_source() -> NewCommittedSource:
    return NewCommittedSource(
        source_id=EXISTING_SOURCE_ID,
        original_filename="existing.txt",
        stored_path="sources/existing.txt",
        source_file_type="txt",
        source_hash="sha256:existing",
        book_number=1,
        committed_at="2026-05-10 18:30:00",
    )


def make_existing_chunk() -> NewChunk:
    return NewChunk(
        chunk_id="existing-chunk-1",
        source_id=EXISTING_SOURCE_ID,
        book_number=1,
        chunk_number=1,
        chunk_text="Existing chunk text.",
        overlap_text="",
        character_start_offset=0,
        character_end_offset=20,
    )


def make_splitter_settings() -> SplitterSettings:
    return SplitterSettings(
        chunk_size=5,
        max_lookback_size=0,
        overlap_size=2,
        splitter_version="ignored-caller-version",
    )


def make_hashed_sources(
    source_files: tuple[Path, Path],
    first_hash: str = "sha256:first",
) -> tuple[HashedStagedSource, ...]:
    return (
        make_hashed_source("entry-1", source_files[0], "txt", first_hash),
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
