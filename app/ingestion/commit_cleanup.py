from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import TypeVar

from app.logger import get_logger

logger = get_logger()

T = TypeVar("T")


class CommitFilePreparationError(ValueError):
    pass


@dataclass(frozen=True)
class CommitFileCopy:
    source_path: Path
    destination_path: Path


@dataclass(frozen=True)
class PreparedCommitFile:
    temporary_path: Path
    destination_path: Path


def run_commit_with_rollback(
    connection: sqlite3.Connection,
    file_copies: Sequence[CommitFileCopy],
    write_database_records: Callable[[sqlite3.Connection], T],
) -> T:
    validate_commit_file_copies(file_copies)
    prepared_files = prepare_commit_file_copies(file_copies)
    promoted_files: list[PreparedCommitFile] = []
    transaction_started = False

    try:
        connection.execute("BEGIN")
        transaction_started = True
        result = write_database_records(connection)
        promoted_files = promote_prepared_commit_files(prepared_files)
        connection.commit()
    except Exception:
        rollback_commit(
            connection,
            transaction_started,
            prepared_files,
            promoted_files,
        )
        raise

    return result


def validate_commit_file_copies(file_copies: Sequence[CommitFileCopy]) -> None:
    destination_paths: set[Path] = set()

    for file_copy in file_copies:
        destination_path = file_copy.destination_path.resolve()
        if destination_path in destination_paths:
            logger.warning("Rejected duplicate commit file destination.")
            raise CommitFilePreparationError(
                "Commit file destinations must be unique."
            )

        if destination_path.exists():
            logger.warning("Rejected existing commit file destination.")
            raise CommitFilePreparationError(
                "Commit file destination already exists."
            )

        destination_paths.add(destination_path)


def prepare_commit_file_copies(
    file_copies: Sequence[CommitFileCopy],
) -> list[PreparedCommitFile]:
    prepared_files: list[PreparedCommitFile] = []

    try:
        for file_copy in file_copies:
            prepared_files.append(prepare_commit_file_copy(file_copy))
    except Exception:
        cleanup_commit_files(prepared_files, [])
        raise

    return prepared_files


def prepare_commit_file_copy(file_copy: CommitFileCopy) -> PreparedCommitFile:
    destination_parent = file_copy.destination_path.parent
    temporary_path: Path | None = None

    try:
        destination_parent.mkdir(parents=True, exist_ok=True)
        temporary_file = tempfile.NamedTemporaryFile(
            dir=destination_parent,
            prefix=f".{file_copy.destination_path.name}.",
            suffix=".tmp",
            delete=False,
        )
        with temporary_file:
            temporary_path = Path(temporary_file.name)

        shutil.copy2(file_copy.source_path, temporary_path)
    except Exception:
        if temporary_path is not None:
            cleanup_commit_files(
                [PreparedCommitFile(temporary_path, file_copy.destination_path)],
                [],
            )
        raise

    return PreparedCommitFile(
        temporary_path=temporary_path,
        destination_path=file_copy.destination_path,
    )


def promote_prepared_commit_files(
    prepared_files: Sequence[PreparedCommitFile],
) -> list[PreparedCommitFile]:
    promoted_files: list[PreparedCommitFile] = []

    for prepared_file in prepared_files:
        if prepared_file.destination_path.exists():
            raise FileExistsError("Commit file destination already exists.")

        prepared_file.temporary_path.rename(prepared_file.destination_path)
        promoted_files.append(prepared_file)

    return promoted_files


def rollback_commit(
    connection: sqlite3.Connection,
    transaction_started: bool,
    prepared_files: Sequence[PreparedCommitFile],
    promoted_files: Sequence[PreparedCommitFile],
) -> None:
    logger.warning(
        "Commit rollback started: prepared_file_count=%s promoted_file_count=%s",
        len(prepared_files),
        len(promoted_files),
    )

    if transaction_started:
        try:
            connection.rollback()
        except sqlite3.Error:
            logger.error(
                "Failed to roll back commit database transaction.",
                exc_info=True,
            )

    cleanup_commit_files(prepared_files, promoted_files)
    logger.warning(
        "Commit rollback completed: prepared_file_count=%s promoted_file_count=%s",
        len(prepared_files),
        len(promoted_files),
    )


def cleanup_commit_files(
    prepared_files: Sequence[PreparedCommitFile],
    promoted_files: Sequence[PreparedCommitFile],
) -> None:
    for prepared_file in prepared_files:
        cleanup_path(prepared_file.temporary_path)

    for promoted_file in promoted_files:
        cleanup_path(promoted_file.destination_path)

    remaining_count = count_remaining_commit_files(prepared_files, promoted_files)
    if remaining_count > 0:
        logger.critical(
            "Unrecoverable commit cleanup inconsistency: remaining_file_count=%s",
            remaining_count,
        )


def cleanup_path(path: Path) -> None:
    if not path.exists():
        return

    try:
        path.unlink()
    except OSError as error:
        logger.error(
            "Failed to clean commit file: error_type=%s",
            type(error).__name__,
        )


def count_remaining_commit_files(
    prepared_files: Sequence[PreparedCommitFile],
    promoted_files: Sequence[PreparedCommitFile],
) -> int:
    tracked_paths = {
        *(prepared_file.temporary_path for prepared_file in prepared_files),
        *(promoted_file.destination_path for promoted_file in promoted_files),
    }
    return sum(1 for path in tracked_paths if path.exists())
