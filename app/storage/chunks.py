from collections.abc import Sequence
from dataclasses import dataclass
import sqlite3
from typing import Any, NoReturn

from app.logger import get_logger

logger = get_logger()


class ChunkValidationError(ValueError):
    pass


class DuplicateChunkError(ChunkValidationError):
    pass


@dataclass(frozen=True)
class NewChunk:
    chunk_id: str
    source_id: str
    book_number: int
    chunk_number: int
    chunk_text: str
    overlap_text: str
    character_start_offset: int | None = None
    character_end_offset: int | None = None


@dataclass(frozen=True)
class StoredChunk:
    chunk_id: str
    source_id: str
    book_number: int
    chunk_number: int
    chunk_text: str
    overlap_text: str
    character_start_offset: int | None
    character_end_offset: int | None


def append_chunks(
    connection: sqlite3.Connection,
    chunks: Sequence[NewChunk],
) -> list[StoredChunk]:
    stored_chunks = [stored_chunk_from_new_chunk(chunk) for chunk in chunks]
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
        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        logger.error("Failed to append chunk batch.", exc_info=True)
        raise

    logger.info("Appended chunk batch: count=%s", len(stored_chunks))
    logger.debug(
        "Appended chunk batch IDs: count=%s chunk_ids=%s",
        len(stored_chunks),
        [chunk.chunk_id for chunk in stored_chunks],
    )
    return stored_chunks


def list_chunks(connection: sqlite3.Connection) -> list[StoredChunk]:
    try:
        rows = connection.execute(
            """
            SELECT
                chunk_id,
                source_id,
                book_number,
                chunk_number,
                chunk_text,
                overlap_text,
                character_start_offset,
                character_end_offset
            FROM chunks
            ORDER BY book_number, chunk_number, chunk_id
            """
        ).fetchall()
    except sqlite3.Error:
        logger.error("Failed to list chunks.", exc_info=True)
        raise

    logger.debug("Listed chunks: count=%s", len(rows))
    return [stored_chunk_from_row(row) for row in rows]


def stored_chunk_from_new_chunk(chunk: NewChunk) -> StoredChunk:
    validate_new_chunk(chunk)
    return StoredChunk(
        chunk_id=chunk.chunk_id,
        source_id=chunk.source_id,
        book_number=chunk.book_number,
        chunk_number=chunk.chunk_number,
        chunk_text=chunk.chunk_text,
        overlap_text=chunk.overlap_text,
        character_start_offset=chunk.character_start_offset,
        character_end_offset=chunk.character_end_offset,
    )


def validate_new_chunk(chunk: NewChunk) -> NewChunk:
    if not has_text_value(chunk.chunk_id):
        reject_invalid_chunk("Chunk ID is required.")

    if not has_text_value(chunk.source_id):
        reject_invalid_chunk("Chunk source ID is required.")

    if type(chunk.book_number) is not int or chunk.book_number < 1:
        reject_invalid_chunk("Chunk book number is invalid.")

    if type(chunk.chunk_number) is not int or chunk.chunk_number < 1:
        reject_invalid_chunk("Chunk number is invalid.")

    if not has_text_value(chunk.chunk_text):
        reject_invalid_chunk("Chunk text is required.")

    if type(chunk.overlap_text) is not str:
        reject_invalid_chunk("Chunk overlap text is invalid.")

    if not is_valid_offset(chunk.character_start_offset):
        reject_invalid_chunk("Chunk start offset is invalid.")

    if not is_valid_offset(chunk.character_end_offset):
        reject_invalid_chunk("Chunk end offset is invalid.")

    if has_invalid_offset_range(
        chunk.character_start_offset,
        chunk.character_end_offset,
    ):
        reject_invalid_chunk("Chunk offset range is invalid.")

    return chunk


def reject_duplicate_chunks_in_batch(chunks: Sequence[StoredChunk]) -> None:
    chunk_ids: set[str] = set()
    chunk_positions: set[tuple[int, int]] = set()

    for chunk in chunks:
        if chunk.chunk_id in chunk_ids:
            logger.warning("Rejected duplicate chunk ID.")
            raise DuplicateChunkError("Chunk ID already exists in batch.")

        chunk_position = (chunk.book_number, chunk.chunk_number)
        if chunk_position in chunk_positions:
            logger.warning("Rejected duplicate chunk position.")
            raise DuplicateChunkError("Chunk book and chunk number already exist in batch.")

        chunk_ids.add(chunk.chunk_id)
        chunk_positions.add(chunk_position)


def reject_existing_chunks(
    connection: sqlite3.Connection,
    chunks: Sequence[StoredChunk],
) -> None:
    if not chunks:
        return

    try:
        for chunk in chunks:
            row = connection.execute(
                """
                SELECT chunk_id, book_number, chunk_number
                FROM chunks
                WHERE chunk_id = ?
                   OR (book_number = ? AND chunk_number = ?)
                """,
                (chunk.chunk_id, chunk.book_number, chunk.chunk_number),
            ).fetchone()

            if row is None:
                continue

            if row["chunk_id"] == chunk.chunk_id:
                logger.warning("Rejected duplicate chunk ID.")
                raise DuplicateChunkError("Chunk ID already exists.")

            logger.warning("Rejected duplicate chunk position.")
            raise DuplicateChunkError("Chunk book and chunk number already exist.")
    except sqlite3.Error:
        logger.error("Failed to check existing chunks.", exc_info=True)
        raise


def reject_invalid_chunk(message: str) -> NoReturn:
    logger.warning("Invalid chunk metadata: %s", message)
    raise ChunkValidationError(message)


def has_text_value(value: Any) -> bool:
    return type(value) is str and bool(value.strip())


def is_valid_offset(value: Any) -> bool:
    return value is None or (type(value) is int and value >= 0)


def has_invalid_offset_range(
    start_offset: int | None,
    end_offset: int | None,
) -> bool:
    return (
        start_offset is not None
        and end_offset is not None
        and end_offset < start_offset
    )


def stored_chunk_from_row(row: sqlite3.Row) -> StoredChunk:
    return StoredChunk(
        chunk_id=row["chunk_id"],
        source_id=row["source_id"],
        book_number=row["book_number"],
        chunk_number=row["chunk_number"],
        chunk_text=row["chunk_text"],
        overlap_text=row["overlap_text"],
        character_start_offset=row["character_start_offset"],
        character_end_offset=row["character_end_offset"],
    )
