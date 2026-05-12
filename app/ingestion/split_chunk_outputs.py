from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
import sqlite3

from app.draft_worlds.splitter_settings import (
    SplitterSettings,
    validate_splitter_settings,
)
from app.ingestion.attempt_workspace import TemporaryIngestionWorkspace
from app.ingestion.parsed_source_outputs import TemporaryParsedSourceOutput
from app.ingestion.splitting.main_chunks import iter_main_chunks
from app.logger import get_logger

logger = get_logger()

SPLIT_CHUNKS_DATABASE_NAME = "split_chunks.sqlite"


class SplitChunkOutputPreparationError(RuntimeError):
    pass


class SplitChunkOutputReadError(RuntimeError):
    pass


@dataclass(frozen=True)
class TemporarySplitChunkSourceSummary:
    staging_entry_id: str
    source_file_type: str
    chunk_count: int


@dataclass(frozen=True)
class TemporarySplitChunkOutputSummary:
    attempt_id: str
    database_path: Path
    source_count: int
    chunk_count: int
    sources: tuple[TemporarySplitChunkSourceSummary, ...]


@dataclass(frozen=True)
class TemporarySplitChunkOutput:
    source_order: int
    attempt_id: str
    staging_entry_id: str
    source_file_type: str
    chunk_number: int
    chunk_text: str
    overlap_text: str
    character_start_offset: int | None
    character_end_offset: int | None
    splitter_version: str


def prepare_split_chunk_outputs(
    workspace: TemporaryIngestionWorkspace,
    parsed_outputs: Sequence[TemporaryParsedSourceOutput],
    splitter_settings: SplitterSettings,
) -> TemporarySplitChunkOutputSummary:
    database_path = resolve_split_chunk_database_path(workspace)
    connection: sqlite3.Connection | None = None

    try:
        validated_settings = validate_splitter_settings(splitter_settings)
        cleanup_split_chunk_database(database_path)
        connection = sqlite3.connect(database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        create_split_chunk_schema(connection)
        summary = write_split_chunk_outputs(
            connection,
            workspace,
            parsed_outputs,
            validated_settings,
            database_path,
        )
        connection.commit()
    except Exception as error:
        if connection is not None:
            rollback_split_chunk_output_preparation(connection)
            connection.close()
            connection = None

        cleanup_split_chunk_database(database_path)
        logger.error(
            "Failed to prepare temporary split chunk outputs: "
            "attempt_id=%s error_type=%s",
            workspace.attempt_id,
            type(error).__name__,
        )
        raise SplitChunkOutputPreparationError(
            "Failed to prepare temporary split chunk outputs."
        ) from error
    finally:
        if connection is not None:
            connection.close()

    logger.info(
        "Prepared temporary split chunk outputs: "
        "attempt_id=%s source_count=%s chunk_count=%s",
        summary.attempt_id,
        summary.source_count,
        summary.chunk_count,
    )
    return summary


def resolve_split_chunk_database_path(workspace: TemporaryIngestionWorkspace) -> Path:
    return Path(workspace.workspace_path) / SPLIT_CHUNKS_DATABASE_NAME


def cleanup_split_chunk_database(database_path: Path) -> None:
    for path in (
        database_path,
        database_path.with_name(f"{database_path.name}-journal"),
        database_path.with_name(f"{database_path.name}-wal"),
        database_path.with_name(f"{database_path.name}-shm"),
    ):
        if path.exists():
            path.unlink()


def rollback_split_chunk_output_preparation(connection: sqlite3.Connection) -> None:
    try:
        connection.rollback()
    except sqlite3.Error:
        logger.error("Failed to roll back temporary split chunk outputs.")


def create_split_chunk_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE split_chunk_outputs (
            source_order INTEGER NOT NULL CHECK (source_order >= 0),
            attempt_id TEXT NOT NULL CHECK (length(trim(attempt_id)) > 0),
            staging_entry_id TEXT NOT NULL CHECK (length(trim(staging_entry_id)) > 0),
            source_file_type TEXT NOT NULL CHECK (length(trim(source_file_type)) > 0),
            chunk_number INTEGER NOT NULL CHECK (chunk_number >= 1),
            chunk_text TEXT NOT NULL,
            overlap_text TEXT NOT NULL,
            character_start_offset INTEGER CHECK (
                character_start_offset IS NULL OR character_start_offset >= 0
            ),
            character_end_offset INTEGER CHECK (
                character_end_offset IS NULL OR character_end_offset >= 0
            ),
            splitter_version TEXT NOT NULL CHECK (length(trim(splitter_version)) > 0),
            UNIQUE (staging_entry_id, chunk_number),
            CHECK (
                character_start_offset IS NULL
                OR character_end_offset IS NULL
                OR character_end_offset >= character_start_offset
            )
        )
        """
    )


def write_split_chunk_outputs(
    connection: sqlite3.Connection,
    workspace: TemporaryIngestionWorkspace,
    parsed_outputs: Sequence[TemporaryParsedSourceOutput],
    splitter_settings: SplitterSettings,
    database_path: Path,
) -> TemporarySplitChunkOutputSummary:
    source_summaries: list[TemporarySplitChunkSourceSummary] = []
    total_chunk_count = 0

    for source_order, parsed_output in enumerate(parsed_outputs):
        chunk_count = write_split_chunk_output_rows(
            connection,
            workspace,
            parsed_output,
            splitter_settings,
            source_order,
        )
        source_summaries.append(
            TemporarySplitChunkSourceSummary(
                staging_entry_id=parsed_output.staging_entry_id,
                source_file_type=parsed_output.source_file_type,
                chunk_count=chunk_count,
            )
        )
        total_chunk_count += chunk_count
        logger.info(
            "Prepared temporary split chunks for source: "
            "attempt_id=%s staging_entry_id=%s source_type=%s chunk_count=%s",
            workspace.attempt_id,
            parsed_output.staging_entry_id,
            parsed_output.source_file_type,
            chunk_count,
        )

    logger.debug(
        "Temporary split chunk output database prepared: "
        "attempt_id=%s source_count=%s chunk_count=%s splitter_version=%s",
        workspace.attempt_id,
        len(source_summaries),
        total_chunk_count,
        splitter_settings.splitter_version,
    )
    return TemporarySplitChunkOutputSummary(
        attempt_id=workspace.attempt_id,
        database_path=database_path,
        source_count=len(source_summaries),
        chunk_count=total_chunk_count,
        sources=tuple(source_summaries),
    )


def write_split_chunk_output_rows(
    connection: sqlite3.Connection,
    workspace: TemporaryIngestionWorkspace,
    parsed_output: TemporaryParsedSourceOutput,
    splitter_settings: SplitterSettings,
    source_order: int,
) -> int:
    chunk_count = 0

    for chunk in iter_main_chunks(parsed_output.parsed_text, splitter_settings):
        insert_split_chunk_output(
            connection,
            TemporarySplitChunkOutput(
                source_order=source_order,
                attempt_id=workspace.attempt_id,
                staging_entry_id=parsed_output.staging_entry_id,
                source_file_type=parsed_output.source_file_type,
                chunk_number=chunk.chunk_number,
                chunk_text=chunk.chunk_text,
                overlap_text=chunk.overlap_text,
                character_start_offset=chunk.character_start_offset,
                character_end_offset=chunk.character_end_offset,
                splitter_version=splitter_settings.splitter_version,
            ),
        )
        chunk_count += 1
        logger.debug(
            "Prepared temporary split chunk row: "
            "attempt_id=%s staging_entry_id=%s chunk_number=%s "
            "character_start_offset=%s character_end_offset=%s splitter_version=%s",
            workspace.attempt_id,
            parsed_output.staging_entry_id,
            chunk.chunk_number,
            chunk.character_start_offset,
            chunk.character_end_offset,
            splitter_settings.splitter_version,
        )

    return chunk_count


def insert_split_chunk_output(
    connection: sqlite3.Connection,
    chunk_output: TemporarySplitChunkOutput,
) -> None:
    connection.execute(
        """
        INSERT INTO split_chunk_outputs (
            source_order,
            attempt_id,
            staging_entry_id,
            source_file_type,
            chunk_number,
            chunk_text,
            overlap_text,
            character_start_offset,
            character_end_offset,
            splitter_version
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chunk_output.source_order,
            chunk_output.attempt_id,
            chunk_output.staging_entry_id,
            chunk_output.source_file_type,
            chunk_output.chunk_number,
            chunk_output.chunk_text,
            chunk_output.overlap_text,
            chunk_output.character_start_offset,
            chunk_output.character_end_offset,
            chunk_output.splitter_version,
        ),
    )


def iter_split_chunk_outputs(
    workspace: TemporaryIngestionWorkspace,
) -> Iterator[TemporarySplitChunkOutput]:
    database_path = resolve_split_chunk_database_path(workspace)
    connection: sqlite3.Connection | None = None

    if not database_path.exists():
        logger.error(
            "Missing temporary split chunk output database: attempt_id=%s",
            workspace.attempt_id,
        )
        raise SplitChunkOutputReadError(
            "Temporary split chunk output database is missing."
        )

    try:
        connection = sqlite3.connect(database_path)
        connection.row_factory = sqlite3.Row
        for row in connection.execute(
            """
            SELECT
                source_order,
                attempt_id,
                staging_entry_id,
                source_file_type,
                chunk_number,
                chunk_text,
                overlap_text,
                character_start_offset,
                character_end_offset,
                splitter_version
            FROM split_chunk_outputs
            ORDER BY source_order, chunk_number
            """
        ):
            yield split_chunk_output_from_row(row)
    except sqlite3.Error as error:
        logger.error(
            "Failed to read temporary split chunk outputs: "
            "attempt_id=%s error_type=%s",
            workspace.attempt_id,
            type(error).__name__,
        )
        raise SplitChunkOutputReadError(
            "Failed to read temporary split chunk outputs."
        ) from error
    finally:
        if connection is not None:
            connection.close()


def split_chunk_output_from_row(row: sqlite3.Row) -> TemporarySplitChunkOutput:
    return TemporarySplitChunkOutput(
        source_order=row["source_order"],
        attempt_id=row["attempt_id"],
        staging_entry_id=row["staging_entry_id"],
        source_file_type=row["source_file_type"],
        chunk_number=row["chunk_number"],
        chunk_text=row["chunk_text"],
        overlap_text=row["overlap_text"],
        character_start_offset=row["character_start_offset"],
        character_end_offset=row["character_end_offset"],
        splitter_version=row["splitter_version"],
    )
