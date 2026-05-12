import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.draft_worlds.splitter_settings import SplitterSettings
from app.ingestion.attempt_workspace import TemporaryIngestionWorkspace
from app.ingestion.parsed_source_outputs import TemporaryParsedSourceOutput
from app.ingestion.split_chunk_outputs import (
    SPLIT_CHUNKS_DATABASE_NAME,
    SplitChunkOutputPreparationError,
    TemporarySplitChunkOutput,
    TemporarySplitChunkOutputSummary,
    TemporarySplitChunkSourceSummary,
    iter_split_chunk_outputs,
    prepare_split_chunk_outputs,
    resolve_split_chunk_database_path,
)
from app.ingestion.splitting import MainChunk, MainChunkGenerationError


class SplitChunkOutputPreparationTests(unittest.TestCase):
    def test_materializes_split_chunks_in_staged_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            workspace = make_workspace(temp_directory)
            parsed_outputs = (
                make_parsed_output("entry-1", "txt", "abcdefghij"),
                make_parsed_output("entry-2", "pdf", "klmnop"),
            )

            summary = prepare_split_chunk_outputs(
                workspace,
                parsed_outputs,
                make_splitter_settings(),
            )
            chunk_outputs = list(iter_split_chunk_outputs(workspace))

        self.assertEqual(
            summary,
            TemporarySplitChunkOutputSummary(
                attempt_id="attempt-1",
                database_path=Path(temp_directory) / SPLIT_CHUNKS_DATABASE_NAME,
                source_count=2,
                chunk_count=4,
                sources=(
                    TemporarySplitChunkSourceSummary("entry-1", "txt", 2),
                    TemporarySplitChunkSourceSummary("entry-2", "pdf", 2),
                ),
            ),
        )
        self.assertEqual(
            chunk_outputs,
            [
                TemporarySplitChunkOutput(
                    source_order=0,
                    attempt_id="attempt-1",
                    staging_entry_id="entry-1",
                    source_file_type="txt",
                    chunk_number=1,
                    chunk_text="abcde",
                    overlap_text="",
                    character_start_offset=0,
                    character_end_offset=5,
                    splitter_version="splitter-v-test",
                ),
                TemporarySplitChunkOutput(
                    source_order=0,
                    attempt_id="attempt-1",
                    staging_entry_id="entry-1",
                    source_file_type="txt",
                    chunk_number=2,
                    chunk_text="fghij",
                    overlap_text="de",
                    character_start_offset=5,
                    character_end_offset=10,
                    splitter_version="splitter-v-test",
                ),
                TemporarySplitChunkOutput(
                    source_order=1,
                    attempt_id="attempt-1",
                    staging_entry_id="entry-2",
                    source_file_type="pdf",
                    chunk_number=1,
                    chunk_text="klmno",
                    overlap_text="",
                    character_start_offset=0,
                    character_end_offset=5,
                    splitter_version="splitter-v-test",
                ),
                TemporarySplitChunkOutput(
                    source_order=1,
                    attempt_id="attempt-1",
                    staging_entry_id="entry-2",
                    source_file_type="pdf",
                    chunk_number=2,
                    chunk_text="p",
                    overlap_text="no",
                    character_start_offset=5,
                    character_end_offset=6,
                    splitter_version="splitter-v-test",
                ),
            ],
        )

    def test_summary_does_not_include_chunk_or_overlap_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            summary = prepare_split_chunk_outputs(
                make_workspace(temp_directory),
                (make_parsed_output("entry-1", "txt", "Do not keep this in summary."),),
                make_splitter_settings(),
            )

        summary_fields = set(summary.__dataclass_fields__)
        source_summary_fields = set(summary.sources[0].__dataclass_fields__)
        self.assertNotIn("chunk_text", summary_fields)
        self.assertNotIn("overlap_text", summary_fields)
        self.assertNotIn("chunk_text", source_summary_fields)
        self.assertNotIn("overlap_text", source_summary_fields)

    def test_empty_input_creates_empty_temporary_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            workspace = make_workspace(temp_directory)

            summary = prepare_split_chunk_outputs(
                workspace,
                (),
                make_splitter_settings(),
            )

            self.assertTrue(resolve_split_chunk_database_path(workspace).exists())
            self.assertEqual(summary.source_count, 0)
            self.assertEqual(summary.chunk_count, 0)
            self.assertEqual(summary.sources, ())
            self.assertEqual(list(iter_split_chunk_outputs(workspace)), [])

    def test_splitter_failure_aborts_and_removes_incomplete_database(self) -> None:
        parsed_text = "Never log this parsed text."

        with tempfile.TemporaryDirectory() as temp_directory:
            workspace = make_workspace(temp_directory)
            database_path = resolve_split_chunk_database_path(workspace)

            with (
                patch(
                    "app.ingestion.split_chunk_outputs.iter_main_chunks",
                    side_effect=failing_chunk_iterator,
                ),
                patch("app.ingestion.split_chunk_outputs.logger") as logger,
            ):
                with self.assertRaises(SplitChunkOutputPreparationError):
                    prepare_split_chunk_outputs(
                        workspace,
                        (make_parsed_output("entry-1", "txt", parsed_text),),
                        make_splitter_settings(),
                    )

            self.assertFalse(database_path.exists())

        logger.error.assert_called()
        self.assertNotIn(parsed_text, repr(logger.method_calls))

    def test_sqlite_write_failure_rolls_back_and_removes_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            workspace = make_workspace(temp_directory)
            database_path = resolve_split_chunk_database_path(workspace)

            with (
                patch(
                    "app.ingestion.split_chunk_outputs.insert_split_chunk_output",
                    side_effect=sqlite3.OperationalError("write failed"),
                ),
                patch("app.ingestion.split_chunk_outputs.logger") as logger,
            ):
                with self.assertRaises(SplitChunkOutputPreparationError):
                    prepare_split_chunk_outputs(
                        workspace,
                        (make_parsed_output("entry-1", "txt", "abcdefghij"),),
                        make_splitter_settings(),
                    )

            self.assertFalse(database_path.exists())
            logger.error.assert_called()

    def test_logs_completion_without_text_or_paths(self) -> None:
        parsed_text = "Never log this chunk text."

        with tempfile.TemporaryDirectory() as temp_directory:
            workspace = make_workspace(temp_directory)

            with patch("app.ingestion.split_chunk_outputs.logger") as logger:
                prepare_split_chunk_outputs(
                    workspace,
                    (make_parsed_output("entry-1", "txt", parsed_text),),
                    make_splitter_settings(),
                )

            log_output = repr(logger.method_calls)

        self.assertIn("Prepared temporary split chunk outputs", log_output)
        self.assertNotIn(parsed_text, log_output)
        self.assertNotIn(temp_directory, log_output)

    def test_does_not_create_world_database_or_source_copies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            workspace = make_workspace(temp_directory)

            prepare_split_chunk_outputs(
                workspace,
                (make_parsed_output("entry-1", "txt", "abcdefghij"),),
                make_splitter_settings(),
            )

            workspace_files = {path.name for path in Path(temp_directory).iterdir()}

        self.assertEqual(workspace_files, {SPLIT_CHUNKS_DATABASE_NAME})
        self.assertNotIn("world.sqlite", workspace_files)
        self.assertNotIn("sources", workspace_files)


def make_workspace(temp_directory: str) -> TemporaryIngestionWorkspace:
    return TemporaryIngestionWorkspace(
        attempt_id="attempt-1",
        workspace_path=Path(temp_directory),
    )


def make_parsed_output(
    staging_entry_id: str,
    source_file_type: str,
    parsed_text: str,
) -> TemporaryParsedSourceOutput:
    return TemporaryParsedSourceOutput(
        attempt_id="attempt-1",
        staging_entry_id=staging_entry_id,
        source_file_type=source_file_type,
        parsed_text=parsed_text,
    )


def make_splitter_settings() -> SplitterSettings:
    return SplitterSettings(
        chunk_size=5,
        max_lookback_size=0,
        overlap_size=2,
        splitter_version="splitter-v-test",
    )


def failing_chunk_iterator(*args: object, **kwargs: object):
    yield MainChunk(
        chunk_number=1,
        chunk_text="first chunk",
        overlap_text="",
        character_start_offset=0,
        character_end_offset=11,
    )
    raise MainChunkGenerationError("splitter failed")


if __name__ == "__main__":
    unittest.main()
