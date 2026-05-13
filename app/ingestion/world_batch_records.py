from collections.abc import Callable
from dataclasses import dataclass
import sqlite3

from app.ingestion.attempt_workspace import TemporaryIngestionWorkspace
from app.ingestion.book_number_assignment import BookNumberAssignment
from app.ingestion.split_chunk_outputs import (
    TemporarySplitChunkOutput,
    iter_split_chunk_outputs,
)
from app.logger import get_logger
from app.storage.chunks import (
    NewChunk,
    StoredChunk,
    reject_duplicate_chunks_in_batch,
    reject_existing_chunks,
    stored_chunk_from_new_chunk,
)
from app.storage.committed_source_files import PreparedCommittedSourceFile
from app.storage.committed_sources import (
    CommittedSource,
    NewCommittedSource,
    reject_duplicate_committed_source,
    validate_new_committed_source,
)
from app.storage.worlds import get_last_used_at_timestamp

logger = get_logger()


class WorldBatchRecordCommitError(RuntimeError):
    pass


@dataclass(frozen=True)
class DurableWorldData:
    committed_sources: tuple[CommittedSource, ...]
    chunks: tuple[StoredChunk, ...]


def write_durable_source_and_chunk_records(
    connection: sqlite3.Connection,
    prepared_sources: tuple[PreparedCommittedSourceFile, ...],
    book_assignments: tuple[BookNumberAssignment, ...],
    workspace: TemporaryIngestionWorkspace,
    chunk_id_factory: Callable[[], str],
) -> DurableWorldData:
    source_records = build_committed_source_records(prepared_sources, book_assignments)
    chunk_records = build_chunk_records(
        workspace,
        prepared_sources,
        book_assignments,
        chunk_id_factory,
    )

    if not chunk_records:
        reject_world_batch_record_commit("Source batches require at least one chunk.")

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
            book_number=assignments_by_staged_id[get_staging_entry_id(prepared_source)],
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
    chunk_id_factory: Callable[[], str],
) -> tuple[NewChunk, ...]:
    source_identity_by_staged_id = get_source_identity_by_staged_id(
        prepared_sources,
        book_assignments,
    )
    source_chunk_counts = {staged_id: 0 for staged_id in source_identity_by_staged_id}
    chunks: list[NewChunk] = []

    for split_chunk in iter_split_chunk_outputs(workspace):
        source_id, book_number = get_source_identity_for_split_chunk(
            split_chunk,
            source_identity_by_staged_id,
        )
        chunks.append(
            NewChunk(
                chunk_id=chunk_id_factory(),
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
            "World batch is missing chunk output for staged sources: count=%s",
            len(missing_chunk_source_ids),
        )
        raise WorldBatchRecordCommitError(
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
    raise WorldBatchRecordCommitError(
        "Temporary split chunk output references an unknown staged source."
    )


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
            reject_world_batch_record_commit("Committed source IDs must be unique.")

        if source.book_number in book_numbers:
            reject_world_batch_record_commit(
                "Committed source book numbers must be unique."
            )

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

    logger.info("Wrote world batch chunk records: count=%s", len(stored_chunks))
    logger.debug(
        "Wrote world batch chunk records: count=%s chunk_ids=%s",
        len(stored_chunks),
        tuple(chunk.chunk_id for chunk in stored_chunks),
    )
    return stored_chunks


def reject_world_batch_record_commit(message: str) -> None:
    logger.error("World batch record commit failed: %s", message)
    raise WorldBatchRecordCommitError(message)
