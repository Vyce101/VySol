from collections.abc import Sequence
from dataclasses import dataclass
import shutil
import sqlite3
from typing import NoReturn
from uuid import uuid4

from app.draft_worlds.splitter_settings import (
    CURRENT_SPLITTER_VERSION,
    SplitterSettings,
    validate_splitter_settings,
)
from app.ingestion.attempt_workspace import TemporaryIngestionWorkspace
from app.ingestion.book_number_assignment import (
    BookNumberAssignment,
    assign_book_numbers_for_staged_sources,
)
from app.ingestion.split_chunk_outputs import (
    TemporarySplitChunkOutput,
    iter_split_chunk_outputs,
)
from app.ingestion.staging.source_duplicate_preflight import (
    validate_no_duplicate_staged_source_hashes,
)
from app.ingestion.staging.source_hash_preflight import HashedStagedSource
from app.logger import get_logger
from app.storage.chunks import (
    NewChunk,
    StoredChunk,
    reject_duplicate_chunks_in_batch,
    reject_existing_chunks,
    stored_chunk_from_new_chunk,
)
from app.storage.committed_source_files import (
    PreparedCommittedSourceFile,
    prepare_committed_source_files,
    run_committed_source_file_commit_with_rollback,
)
from app.storage.committed_sources import (
    CommittedSource,
    NewCommittedSource,
    reject_duplicate_committed_source,
    validate_new_committed_source,
)
from app.storage.database import get_global_connection
from app.storage.world_databases import bootstrap_world_database
from app.storage.world_folders import resolve_world_directory
from app.storage.world_splitter_settings import (
    LOCKED,
    SETTINGS_ID,
    StoredWorldSplitterSettings,
)
from app.storage.worlds import (
    CommittedWorld,
    NewCommittedWorld,
    get_display_name_key,
    get_last_used_at_timestamp,
    reject_duplicate_display_name,
    validate_new_committed_world,
)

logger = get_logger()


class NewWorldBatchCommitError(RuntimeError):
    pass


class NewWorldBatchValidationError(ValueError):
    pass


@dataclass(frozen=True)
class NewWorldBatchCommitResult:
    committed_world: CommittedWorld
    committed_sources: tuple[CommittedSource, ...]
    chunks: tuple[StoredChunk, ...]
    source_count: int
    chunk_count: int


@dataclass(frozen=True)
class DurableWorldData:
    committed_sources: tuple[CommittedSource, ...]
    chunks: tuple[StoredChunk, ...]


def commit_new_world_batch(
    world: NewCommittedWorld,
    splitter_settings: SplitterSettings,
    workspace: TemporaryIngestionWorkspace,
    hashed_sources: Sequence[HashedStagedSource],
    app_connection: sqlite3.Connection | None = None,
) -> NewWorldBatchCommitResult:
    accepted_sources = validate_new_world_batch_inputs(world, hashed_sources)
    world_id = str(uuid4())
    world_connection: sqlite3.Connection | None = None
    world_data: DurableWorldData | None = None

    try:
        world_connection = bootstrap_world_database(world_id)
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
            lambda active_connection, source_files: write_durable_world_data(
                active_connection,
                source_files,
                book_assignments,
                splitter_settings,
                workspace,
            ),
        )
    except Exception as error:
        close_world_connection(world_connection)
        cleanup_new_world_folder(world_id)
        logger.error(
            "Failed to commit new world batch before app index: error_type=%s",
            type(error).__name__,
        )
        raise

    close_world_connection(world_connection)
    committed_world = commit_new_world_index_record(
        app_connection or get_global_connection(),
        world_id,
        world,
    )

    result = NewWorldBatchCommitResult(
        committed_world=committed_world,
        committed_sources=world_data.committed_sources,
        chunks=world_data.chunks,
        source_count=len(world_data.committed_sources),
        chunk_count=len(world_data.chunks),
    )
    logger.info(
        "Committed new world batch: world_id=%s source_count=%s chunk_count=%s",
        committed_world.world_id,
        result.source_count,
        result.chunk_count,
    )
    return result


def validate_new_world_batch_inputs(
    world: NewCommittedWorld,
    hashed_sources: Sequence[HashedStagedSource],
) -> tuple[HashedStagedSource, ...]:
    validate_new_committed_world(world)
    accepted_sources = tuple(hashed_sources)

    if accepted_sources:
        return accepted_sources

    logger.warning("Rejected empty new world batch.")
    raise NewWorldBatchValidationError("New worlds require at least one source.")


def write_durable_world_data(
    connection: sqlite3.Connection,
    prepared_sources: tuple[PreparedCommittedSourceFile, ...],
    book_assignments: tuple[BookNumberAssignment, ...],
    splitter_settings: SplitterSettings,
    workspace: TemporaryIngestionWorkspace,
) -> DurableWorldData:
    source_records = build_committed_source_records(prepared_sources, book_assignments)
    chunk_records = build_chunk_records(workspace, prepared_sources, book_assignments)

    if not chunk_records:
        reject_new_world_batch_commit("New worlds require at least one chunk.")

    insert_locked_world_splitter_settings(connection, splitter_settings)
    committed_sources = insert_committed_source_records(connection, source_records)
    chunks = insert_chunk_records(connection, chunk_records)

    return DurableWorldData(
        committed_sources=tuple(committed_sources),
        chunks=tuple(chunks),
    )


def build_committed_source_records(
    prepared_sources: tuple[PreparedCommittedSourceFile, ...],
    book_assignments: tuple[BookNumberAssignment, ...],
) -> tuple[NewCommittedSource, ...]:
    assignments_by_staged_id = get_book_assignments_by_staged_id(book_assignments)
    committed_at = get_last_used_at_timestamp()

    return tuple(
        NewCommittedSource(
            source_id=prepared_source.source_id,
            original_filename=prepared_source.original_filename,
            stored_path=prepared_source.stored_path,
            source_file_type=prepared_source.source_file_type,
            source_hash=prepared_source.source_hash,
            book_number=assignments_by_staged_id[
                get_staging_entry_id(prepared_source)
            ],
            committed_at=committed_at,
        )
        for prepared_source in prepared_sources
    )


def get_staging_entry_id(prepared_source: PreparedCommittedSourceFile) -> str:
    return prepared_source.staging_entry_id


def get_book_assignments_by_staged_id(
    book_assignments: tuple[BookNumberAssignment, ...],
) -> dict[str, int]:
    return {
        assignment.staging_entry_id: assignment.book_number
        for assignment in book_assignments
    }


def build_chunk_records(
    workspace: TemporaryIngestionWorkspace,
    prepared_sources: tuple[PreparedCommittedSourceFile, ...],
    book_assignments: tuple[BookNumberAssignment, ...],
) -> tuple[NewChunk, ...]:
    source_identity_by_staged_id = get_source_identity_by_staged_id(
        prepared_sources,
        book_assignments,
    )
    source_chunk_counts = {
        staged_id: 0 for staged_id in source_identity_by_staged_id
    }
    chunks: list[NewChunk] = []

    for split_chunk in iter_split_chunk_outputs(workspace):
        source_id, book_number = get_source_identity_for_split_chunk(
            split_chunk,
            source_identity_by_staged_id,
        )
        chunks.append(
            NewChunk(
                chunk_id=str(uuid4()),
                source_id=source_id,
                book_number=book_number,
                chunk_number=split_chunk.chunk_number,
                chunk_text=split_chunk.chunk_text,
                overlap_text=split_chunk.overlap_text,
                character_start_offset=split_chunk.character_start_offset,
                character_end_offset=split_chunk.character_end_offset,
            )
        )
        source_chunk_counts[split_chunk.staging_entry_id] += 1

    missing_chunk_source_ids = tuple(
        staged_id
        for staged_id, chunk_count in source_chunk_counts.items()
        if chunk_count == 0
    )
    if missing_chunk_source_ids:
        logger.error(
            "New world batch is missing chunk output for staged sources: count=%s",
            len(missing_chunk_source_ids),
        )
        raise NewWorldBatchCommitError(
            "Every committed source must have at least one chunk."
        )

    return tuple(chunks)


def get_source_identity_by_staged_id(
    prepared_sources: tuple[PreparedCommittedSourceFile, ...],
    book_assignments: tuple[BookNumberAssignment, ...],
) -> dict[str, tuple[str, int]]:
    book_numbers_by_staged_id = get_book_assignments_by_staged_id(book_assignments)
    source_identity_by_staged_id: dict[str, tuple[str, int]] = {}

    for prepared_source in prepared_sources:
        staged_id = get_staging_entry_id(prepared_source)
        source_identity_by_staged_id[staged_id] = (
            prepared_source.source_id,
            book_numbers_by_staged_id[staged_id],
        )

    return source_identity_by_staged_id


def get_source_identity_for_split_chunk(
    split_chunk: TemporarySplitChunkOutput,
    source_identity_by_staged_id: dict[str, tuple[str, int]],
) -> tuple[str, int]:
    source_identity = source_identity_by_staged_id.get(split_chunk.staging_entry_id)
    if source_identity is not None:
        return source_identity

    logger.error("Temporary split chunk output references an unknown staged source.")
    raise NewWorldBatchCommitError(
        "Temporary split chunk output references an unknown staged source."
    )


def insert_locked_world_splitter_settings(
    connection: sqlite3.Connection,
    splitter_settings: SplitterSettings,
) -> StoredWorldSplitterSettings:
    validated_settings = validate_splitter_settings(splitter_settings)
    stored_settings = StoredWorldSplitterSettings(
        chunk_size=validated_settings.chunk_size,
        max_lookback_size=validated_settings.max_lookback_size,
        overlap_size=validated_settings.overlap_size,
        splitter_version=CURRENT_SPLITTER_VERSION,
        is_locked=True,
    )

    try:
        connection.execute(
            """
            INSERT INTO world_splitter_settings (
                settings_id,
                chunk_size,
                max_lookback_size,
                overlap_size,
                splitter_version,
                is_locked
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                SETTINGS_ID,
                stored_settings.chunk_size,
                stored_settings.max_lookback_size,
                stored_settings.overlap_size,
                stored_settings.splitter_version,
                LOCKED,
            ),
        )
    except sqlite3.Error:
        logger.error("Failed to write locked world splitter settings.")
        raise

    return stored_settings


def insert_committed_source_records(
    connection: sqlite3.Connection,
    source_records: tuple[NewCommittedSource, ...],
) -> tuple[CommittedSource, ...]:
    committed_sources = tuple(
        CommittedSource(
            source_id=source.source_id,
            original_filename=source.original_filename,
            stored_path=source.stored_path,
            source_file_type=source.source_file_type,
            source_hash=source.source_hash,
            book_number=source.book_number,
            committed_at=source.committed_at,
        )
        for source in validate_committed_source_record_batch(
            connection,
            source_records,
        )
    )

    try:
        connection.executemany(
            """
            INSERT INTO committed_sources (
                source_id,
                original_filename,
                stored_path,
                source_file_type,
                source_hash,
                book_number,
                committed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    source.source_id,
                    source.original_filename,
                    source.stored_path,
                    source.source_file_type,
                    source.source_hash,
                    source.book_number,
                    source.committed_at,
                )
                for source in committed_sources
            ],
        )
    except sqlite3.Error:
        logger.error("Failed to write committed source records.")
        raise

    return committed_sources


def validate_committed_source_record_batch(
    connection: sqlite3.Connection,
    source_records: tuple[NewCommittedSource, ...],
) -> tuple[NewCommittedSource, ...]:
    source_ids: set[str] = set()
    book_numbers: set[int] = set()

    for source in source_records:
        validate_new_committed_source(source)
        if source.source_id in source_ids:
            reject_new_world_batch_commit("Committed source IDs must be unique.")

        if source.book_number in book_numbers:
            reject_new_world_batch_commit("Committed source book numbers must be unique.")

        reject_duplicate_committed_source(connection, source)
        source_ids.add(source.source_id)
        book_numbers.add(source.book_number)

    return source_records


def insert_chunk_records(
    connection: sqlite3.Connection,
    chunk_records: tuple[NewChunk, ...],
) -> tuple[StoredChunk, ...]:
    stored_chunks = tuple(stored_chunk_from_new_chunk(chunk) for chunk in chunk_records)
    reject_duplicate_chunks_in_batch(stored_chunks)
    reject_existing_chunks(connection, stored_chunks)

    try:
        connection.executemany(
            """
            INSERT INTO chunks (
                chunk_id,
                source_id,
                book_number,
                chunk_number,
                chunk_text,
                overlap_text,
                character_start_offset,
                character_end_offset
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    chunk.chunk_id,
                    chunk.source_id,
                    chunk.book_number,
                    chunk.chunk_number,
                    chunk.chunk_text,
                    chunk.overlap_text,
                    chunk.character_start_offset,
                    chunk.character_end_offset,
                )
                for chunk in stored_chunks
            ],
        )
    except sqlite3.Error:
        logger.error("Failed to write chunk records.")
        raise

    logger.info("Wrote new world chunk records: count=%s", len(stored_chunks))
    logger.debug(
        "Wrote new world chunk records: count=%s chunk_ids=%s",
        len(stored_chunks),
        tuple(chunk.chunk_id for chunk in stored_chunks),
    )
    return stored_chunks


def commit_new_world_index_record(
    connection: sqlite3.Connection,
    world_id: str,
    world: NewCommittedWorld,
) -> CommittedWorld:
    try:
        connection.execute("BEGIN")
        committed_world = insert_new_world_index_record(connection, world_id, world)
        connection.commit()
    except Exception as error:
        rollback_app_index_commit(connection)
        cleanup_new_world_folder(world_id)
        logger.error(
            "Failed to add committed world index after world data commit: "
            "error_type=%s",
            type(error).__name__,
        )
        raise

    return committed_world


def insert_new_world_index_record(
    connection: sqlite3.Connection,
    world_id: str,
    world: NewCommittedWorld,
) -> CommittedWorld:
    validated_world = validate_new_committed_world(world)
    display_name_key = get_display_name_key(validated_world.display_name)
    last_used_at = get_last_used_at_timestamp()
    reject_duplicate_display_name(
        connection,
        display_name_key,
        "Committed world display name already exists.",
    )
    committed_world = CommittedWorld(
        world_id=world_id,
        display_name=validated_world.display_name,
        description=validated_world.description,
        background_asset_id=validated_world.background_asset_id,
        font_asset_id=validated_world.font_asset_id,
        last_used_at=last_used_at,
    )

    connection.execute(
        """
        INSERT INTO worlds (
            world_id,
            display_name,
            display_name_key,
            description,
            background_asset_id,
            font_asset_id,
            last_used_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            committed_world.world_id,
            committed_world.display_name,
            display_name_key,
            committed_world.description,
            committed_world.background_asset_id,
            committed_world.font_asset_id,
            committed_world.last_used_at,
        ),
    )
    return committed_world


def rollback_app_index_commit(connection: sqlite3.Connection) -> None:
    try:
        connection.rollback()
    except sqlite3.Error:
        logger.critical("Unrecoverable app index rollback failure.")


def cleanup_new_world_folder(world_id: str) -> None:
    world_directory = resolve_world_directory(world_id)
    if not world_directory.exists():
        return

    logger.warning("New world batch cleanup started: world_id=%s", world_id)
    try:
        shutil.rmtree(world_directory)
    except OSError:
        logger.critical(
            "Unrecoverable DB/file consistency failure during new world cleanup: "
            "world_id=%s",
            world_id,
        )
        return

    logger.warning("New world batch cleanup completed: world_id=%s", world_id)


def close_world_connection(connection: sqlite3.Connection | None) -> None:
    if connection is not None:
        connection.close()


def reject_new_world_batch_commit(message: str) -> NoReturn:
    logger.error("New world batch commit failed: %s", message)
    raise NewWorldBatchCommitError(message)
