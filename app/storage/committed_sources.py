from dataclasses import dataclass
import sqlite3
from typing import Any, NoReturn

from app.logger import get_logger

logger = get_logger()


class CommittedSourceValidationError(ValueError):
    pass


class DuplicateCommittedSourceError(CommittedSourceValidationError):
    pass


@dataclass(frozen=True)
class NewCommittedSource:
    source_id: str
    original_filename: str
    stored_path: str
    source_file_type: str
    source_hash: str
    book_number: int
    committed_at: str


@dataclass(frozen=True)
class CommittedSource:
    source_id: str
    original_filename: str
    stored_path: str
    source_file_type: str
    source_hash: str
    book_number: int
    committed_at: str


def append_committed_source(
    connection: sqlite3.Connection,
    source: NewCommittedSource,
) -> CommittedSource:
    validated_source = validate_new_committed_source(source)
    reject_duplicate_committed_source(connection, validated_source)
    committed_source = CommittedSource(
        source_id=validated_source.source_id,
        original_filename=validated_source.original_filename,
        stored_path=validated_source.stored_path,
        source_file_type=validated_source.source_file_type,
        source_hash=validated_source.source_hash,
        book_number=validated_source.book_number,
        committed_at=validated_source.committed_at,
    )

    try:
        connection.execute(
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
            (
                committed_source.source_id,
                committed_source.original_filename,
                committed_source.stored_path,
                committed_source.source_file_type,
                committed_source.source_hash,
                committed_source.book_number,
                committed_source.committed_at,
            ),
        )
        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        logger.error("Failed to append committed source metadata.", exc_info=True)
        raise

    logger.info("Appended committed source metadata.")
    logger.debug(
        "Appended committed source metadata: %s %s",
        committed_source.source_id,
        committed_source.book_number,
    )
    return committed_source


def list_committed_sources(connection: sqlite3.Connection) -> list[CommittedSource]:
    try:
        rows = connection.execute(
            """
            SELECT
                source_id,
                original_filename,
                stored_path,
                source_file_type,
                source_hash,
                book_number,
                committed_at
            FROM committed_sources
            ORDER BY book_number, source_id
            """
        ).fetchall()
    except sqlite3.Error:
        logger.error("Failed to list committed source metadata.", exc_info=True)
        raise

    return [committed_source_from_row(row) for row in rows]


def validate_new_committed_source(source: NewCommittedSource) -> NewCommittedSource:
    if not has_text_value(source.source_id):
        reject_invalid_committed_source("Committed source ID is required.")

    if not has_text_value(source.original_filename):
        reject_invalid_committed_source("Committed source original filename is required.")

    if not has_text_value(source.stored_path):
        reject_invalid_committed_source("Committed source stored path is required.")

    if not has_text_value(source.source_file_type):
        reject_invalid_committed_source("Committed source file type is required.")

    if not has_text_value(source.source_hash):
        reject_invalid_committed_source("Committed source hash is required.")

    if type(source.book_number) is not int or source.book_number < 1:
        reject_invalid_committed_source("Committed source book number is invalid.")

    if not has_text_value(source.committed_at):
        reject_invalid_committed_source("Committed source timestamp is required.")

    return source


def reject_duplicate_committed_source(
    connection: sqlite3.Connection,
    source: NewCommittedSource,
) -> None:
    try:
        row = connection.execute(
            """
            SELECT source_id, book_number
            FROM committed_sources
            WHERE source_id = ? OR book_number = ?
            """,
            (source.source_id, source.book_number),
        ).fetchone()
    except sqlite3.Error:
        logger.error("Failed to check committed source metadata.", exc_info=True)
        raise

    if row is None:
        return

    if row["source_id"] == source.source_id:
        logger.warning("Rejected duplicate committed source ID.")
        raise DuplicateCommittedSourceError("Committed source ID already exists.")

    logger.warning("Rejected duplicate committed source book number.")
    raise DuplicateCommittedSourceError("Committed source book number already exists.")


def reject_invalid_committed_source(message: str) -> NoReturn:
    logger.warning("Invalid committed source metadata: %s", message)
    raise CommittedSourceValidationError(message)


def has_text_value(value: Any) -> bool:
    return type(value) is str and bool(value.strip())


def committed_source_from_row(row: sqlite3.Row) -> CommittedSource:
    return CommittedSource(
        source_id=row["source_id"],
        original_filename=row["original_filename"],
        stored_path=row["stored_path"],
        source_file_type=row["source_file_type"],
        source_hash=row["source_hash"],
        book_number=row["book_number"],
        committed_at=row["committed_at"],
    )
