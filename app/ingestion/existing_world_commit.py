from collections.abc import Sequence
from dataclasses import dataclass
import sqlite3
from uuid import uuid4

from app.ingestion.attempt_workspace import TemporaryIngestionWorkspace
from app.ingestion.book_number_assignment import (
    BookNumberAssignment,
    assign_book_numbers_for_staged_sources,
)
from app.ingestion.staging.source_duplicate_preflight import (
    validate_no_duplicate_staged_source_hashes,
)
from app.ingestion.staging.source_hash_preflight import HashedStagedSource
from app.ingestion.world_batch_records import (
    DurableWorldData,
    WorldBatchRecordCommitError,
    write_durable_source_and_chunk_records,
)
from app.logger import get_logger
from app.storage.chunks import StoredChunk
from app.storage.committed_source_files import (
    PreparedCommittedSourceFile,
    prepare_committed_source_files,
    run_committed_source_file_commit_with_rollback,
)
from app.storage.committed_sources import CommittedSource
from app.storage.database import get_global_connection
from app.storage.world_databases import open_world_database
from app.storage.worlds import get_committed_world, mark_committed_world_used

logger = get_logger()


class ExistingWorldBatchCommitError(RuntimeError):
    pass


class ExistingWorldBatchValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ExistingWorldBatchCommitResult:
    committed_sources: tuple[CommittedSource, ...]
    chunks: tuple[StoredChunk, ...]
    source_count: int
    chunk_count: int
    last_used_at_refreshed: bool


def commit_existing_world_batch(
    world_id: str,
    workspace: TemporaryIngestionWorkspace,
    hashed_sources: Sequence[HashedStagedSource],
    app_connection: sqlite3.Connection | None = None,
) -> ExistingWorldBatchCommitResult:
    app_database = app_connection or get_global_connection()
    accepted_sources = validate_existing_world_batch_inputs(
        world_id,
        hashed_sources,
        app_database,
    )
    world_connection: sqlite3.Connection | None = None
    world_data: DurableWorldData | None = None

    try:
        world_connection = open_world_database(world_id)
        validate_no_duplicate_staged_source_hashes(world_connection, accepted_sources)
        prepared_sources = prepare_committed_source_files(world_id, accepted_sources)
        book_assignments = assign_book_numbers_for_staged_sources(
            world_connection,
            tuple(
                hashed_source.staged_source.staging_entry_id
                for hashed_source in accepted_sources
            ),
        )
        world_data = run_committed_source_file_commit_with_rollback(
            world_connection,
            prepared_sources,
            lambda active_connection, source_files: write_existing_world_data(
                active_connection,
                source_files,
                book_assignments,
                workspace,
            ),
        )
    except Exception as error:
        close_world_connection(world_connection)
        logger.error(
            "Failed to commit existing world batch: error_type=%s",
            type(error).__name__,
        )
        raise

    close_world_connection(world_connection)
    last_used_at_refreshed = refresh_existing_world_last_used_at(
        world_id,
        app_database,
    )
    result = ExistingWorldBatchCommitResult(
        committed_sources=world_data.committed_sources,
        chunks=world_data.chunks,
        source_count=len(world_data.committed_sources),
        chunk_count=len(world_data.chunks),
        last_used_at_refreshed=last_used_at_refreshed,
    )
    logger.info(
        "Committed existing world batch: world_id=%s source_count=%s chunk_count=%s",
        world_id,
        result.source_count,
        result.chunk_count,
    )
    return result


def validate_existing_world_batch_inputs(
    world_id: str,
    hashed_sources: Sequence[HashedStagedSource],
    app_connection: sqlite3.Connection,
) -> tuple[HashedStagedSource, ...]:
    if get_committed_world(world_id, app_connection) is None:
        logger.error("Missing committed world index record for source commit.")
        raise ExistingWorldBatchValidationError(
            "Existing world source commits require a committed world."
        )

    accepted_sources = tuple(hashed_sources)
    if accepted_sources:
        return accepted_sources

    logger.warning("Rejected empty existing world batch.")
    raise ExistingWorldBatchValidationError(
        "Existing world source commits require at least one source."
    )


def write_existing_world_data(
    connection: sqlite3.Connection,
    prepared_sources: tuple[PreparedCommittedSourceFile, ...],
    book_assignments: tuple[BookNumberAssignment, ...],
    workspace: TemporaryIngestionWorkspace,
) -> DurableWorldData:
    try:
        return write_durable_source_and_chunk_records(
            connection,
            prepared_sources,
            book_assignments,
            workspace,
            lambda: str(uuid4()),
        )
    except WorldBatchRecordCommitError as error:
        raise ExistingWorldBatchCommitError(str(error)) from error


def refresh_existing_world_last_used_at(
    world_id: str,
    app_connection: sqlite3.Connection,
) -> bool:
    try:
        refreshed_world = mark_committed_world_used(world_id, connection=app_connection)
    except Exception as error:
        logger.error(
            "Failed to refresh existing world last_used_at after source commit: "
            "error_type=%s",
            type(error).__name__,
        )
        return False

    if refreshed_world is not None:
        return True

    logger.error("Missing committed world index record after source commit.")
    return False


def close_world_connection(connection: sqlite3.Connection | None) -> None:
    if connection is not None:
        connection.close()
