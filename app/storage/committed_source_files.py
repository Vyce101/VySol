from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
import sqlite3
from typing import TypeVar
from uuid import uuid4

from app.ingestion.commit_cleanup import CommitFileCopy, run_commit_with_rollback
from app.ingestion.staging.source_hash_preflight import HashedStagedSource
from app.logger import get_logger
from app.storage.world_folders import (
    SOURCES_DIRECTORY_NAME,
    normalize_world_id,
    resolve_world_sources_directory,
)

logger = get_logger()

SAFE_SOURCE_SUFFIX_PATTERN = re.compile(r"^\.[A-Za-z0-9]{1,16}$")

T = TypeVar("T")


@dataclass(frozen=True)
class PreparedCommittedSourceFile:
    source_id: str
    original_filename: str
    stored_path: str
    source_file_type: str
    source_hash: str
    file_copy: CommitFileCopy


def prepare_committed_source_files(
    world_id: str,
    hashed_sources: Sequence[HashedStagedSource],
) -> tuple[PreparedCommittedSourceFile, ...]:
    normalized_world_id = normalize_world_id(world_id)
    sources_directory = resolve_world_sources_directory(normalized_world_id)
    prepared_sources = tuple(
        prepare_committed_source_file(sources_directory, hashed_source)
        for hashed_source in hashed_sources
    )
    source_ids = tuple(source.source_id for source in prepared_sources)

    logger.info(
        "Prepared committed source file copies: world_id=%s count=%s source_ids=%s",
        normalized_world_id,
        len(prepared_sources),
        source_ids,
    )
    return prepared_sources


def prepare_committed_source_file(
    sources_directory: Path,
    hashed_source: HashedStagedSource,
) -> PreparedCommittedSourceFile:
    source_id = str(uuid4())
    source_file_path = Path(hashed_source.staged_source.source_file_path)
    original_filename = source_file_path.name
    safe_suffix = get_safe_source_filename_suffix(original_filename)
    destination_path = sources_directory / f"{source_id}{safe_suffix}"
    ensure_path_is_inside_directory(destination_path, sources_directory)

    return PreparedCommittedSourceFile(
        source_id=source_id,
        original_filename=original_filename,
        stored_path=get_world_source_stored_path(destination_path.name),
        source_file_type=hashed_source.staged_source.source_file_type,
        source_hash=hashed_source.source_hash,
        file_copy=CommitFileCopy(
            source_path=source_file_path,
            destination_path=destination_path,
        ),
    )


def run_committed_source_file_commit_with_rollback(
    connection: sqlite3.Connection,
    prepared_sources: Sequence[PreparedCommittedSourceFile],
    write_database_records: Callable[
        [sqlite3.Connection, tuple[PreparedCommittedSourceFile, ...]], T
    ],
) -> T:
    source_files = tuple(prepared_sources)
    file_copies = tuple(source.file_copy for source in source_files)

    try:
        result = run_commit_with_rollback(
            connection,
            file_copies,
            lambda active_connection: write_database_records(
                active_connection,
                source_files,
            ),
        )
    except OSError as error:
        logger.error(
            "Failed to copy committed source files: count=%s source_ids=%s "
            "error_type=%s",
            len(source_files),
            tuple(source.source_id for source in source_files),
            type(error).__name__,
        )
        raise

    logger.info(
        "Copied committed source files: count=%s source_ids=%s",
        len(source_files),
        tuple(source.source_id for source in source_files),
    )
    return result


def get_safe_source_filename_suffix(original_filename: str) -> str:
    suffix = Path(original_filename).suffix
    if not suffix:
        return ""

    if SAFE_SOURCE_SUFFIX_PATTERN.fullmatch(suffix):
        return suffix.lower()

    logger.warning("Unsupported committed source filename suffix ignored.")
    return ""


def get_world_source_stored_path(stored_filename: str) -> str:
    return PurePosixPath(SOURCES_DIRECTORY_NAME, stored_filename).as_posix()


def ensure_path_is_inside_directory(path: Path, directory: Path) -> None:
    resolved_path = path.resolve()
    resolved_directory = directory.resolve()
    if resolved_path.is_relative_to(resolved_directory):
        return

    logger.warning("Rejected unsafe committed source storage path.")
    raise ValueError("Committed source storage path must stay inside sources.")
