from collections.abc import Sequence
from dataclasses import dataclass
import sqlite3
from typing import Any, NoReturn

from app.logger import get_logger

logger = get_logger()

DEFAULT_STARTING_BOOK_NUMBER = 1


class BookNumberAssignmentError(ValueError):
    pass


@dataclass(frozen=True)
class BookNumberAssignment:
    staging_entry_id: str
    book_number: int


def assign_book_numbers_for_staged_sources(
    connection: sqlite3.Connection,
    staged_source_ids: Sequence[str],
) -> tuple[BookNumberAssignment, ...]:
    staged_ids = validate_staged_source_ids(staged_source_ids)
    if not staged_ids:
        logger.debug("Assigned book numbers: count=0")
        return ()

    first_book_number = get_next_book_number(connection)
    last_book_number = first_book_number + len(staged_ids) - 1
    reject_existing_book_number_conflicts(
        connection,
        first_book_number,
        last_book_number,
    )

    assignments = tuple(
        BookNumberAssignment(
            staging_entry_id=staged_id,
            book_number=first_book_number + index,
        )
        for index, staged_id in enumerate(staged_ids)
    )
    logger.info(
        "Assigned book numbers: first=%s last=%s count=%s",
        first_book_number,
        last_book_number,
        len(assignments),
    )
    return assignments


def validate_staged_source_ids(staged_source_ids: Sequence[str]) -> tuple[str, ...]:
    staged_ids = tuple(staged_source_ids)
    seen_ids: set[str] = set()

    for staged_id in staged_ids:
        if not has_text_value(staged_id):
            reject_book_number_assignment("Staged source ID is required.")

        if staged_id in seen_ids:
            reject_book_number_assignment("Staged source IDs must be unique.")

        seen_ids.add(staged_id)

    return staged_ids


def get_next_book_number(connection: sqlite3.Connection) -> int:
    try:
        row = connection.execute(
            """
            SELECT MAX(book_number) AS highest_book_number
            FROM committed_sources
            """
        ).fetchone()
    except sqlite3.Error:
        logger.error(
            "Failed to read highest committed source book number.",
            exc_info=True,
        )
        raise

    highest_book_number = row[0] if row is not None else None
    if highest_book_number is None:
        return DEFAULT_STARTING_BOOK_NUMBER

    if type(highest_book_number) is not int or highest_book_number < 1:
        reject_book_number_assignment("Committed source book numbering is invalid.")

    return highest_book_number + 1


def reject_existing_book_number_conflicts(
    connection: sqlite3.Connection,
    first_book_number: int,
    last_book_number: int,
) -> None:
    try:
        rows = connection.execute(
            """
            SELECT book_number
            FROM committed_sources
            WHERE book_number BETWEEN ? AND ?
            LIMIT 1
            """,
            (first_book_number, last_book_number),
        ).fetchall()
    except sqlite3.Error:
        logger.error(
            "Failed to check committed source book number conflicts.",
            exc_info=True,
        )
        raise

    if rows:
        reject_book_number_assignment(
            "Assigned book number range conflicts with committed sources."
        )


def reject_book_number_assignment(message: str) -> NoReturn:
    logger.error("Book number assignment failed: %s", message)
    raise BookNumberAssignmentError(message)


def has_text_value(value: Any) -> bool:
    return type(value) is str and bool(value.strip())
