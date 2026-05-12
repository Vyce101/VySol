from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
from pathlib import Path

from app.ingestion.staging.source_staging_state import TemporarySourceStagingEntry
from app.logger import get_logger

logger = get_logger()

SOURCE_HASH_ALGORITHM = "sha256"
SOURCE_HASH_READ_SIZE = 1024 * 1024


@dataclass(frozen=True)
class HashedStagedSource:
    staged_source: TemporarySourceStagingEntry
    source_hash: str


def hash_staged_source_files(
    entries: Sequence[TemporarySourceStagingEntry],
) -> tuple[HashedStagedSource, ...]:
    hashed_sources = tuple(hash_staged_source_file(entry) for entry in entries)
    logger.info("Hashed staged source files: count=%s", len(hashed_sources))
    return hashed_sources


def hash_staged_source_file(entry: TemporarySourceStagingEntry) -> HashedStagedSource:
    return HashedStagedSource(
        staged_source=entry,
        source_hash=calculate_staged_source_file_hash(entry),
    )


def calculate_staged_source_file_hash(entry: TemporarySourceStagingEntry) -> str:
    file_hasher = hashlib.sha256()

    try:
        source_file_path = Path(entry.source_file_path)
        with source_file_path.open("rb") as source_file:
            while chunk := source_file.read(SOURCE_HASH_READ_SIZE):
                file_hasher.update(chunk)
    except OSError as error:
        logger.error(
            "Failed to hash staged source file: "
            "staging_entry_id=%s source_type=%s error_type=%s",
            entry.staging_entry_id,
            entry.source_file_type,
            type(error).__name__,
        )
        raise
    except Exception as error:
        logger.error(
            "Unexpected staged source hash failure: "
            "staging_entry_id=%s source_type=%s error_type=%s",
            entry.staging_entry_id,
            entry.source_file_type,
            type(error).__name__,
        )
        raise RuntimeError("Unexpected staged source hash failure.") from error

    return f"{SOURCE_HASH_ALGORITHM}:{file_hasher.hexdigest()}"
