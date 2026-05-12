from collections.abc import Sequence
import sqlite3

from app.ingestion.staging.source_hash_preflight import HashedStagedSource
from app.logger import get_logger

logger = get_logger()

HASH_LOG_PREFIX_LENGTH = 19


class DuplicateStagedSourceError(ValueError):
    pass


def validate_no_duplicate_staged_source_hashes(
    connection: sqlite3.Connection,
    hashed_sources: Sequence[HashedStagedSource],
) -> tuple[HashedStagedSource, ...]:
    staged_sources = tuple(hashed_sources)
    reject_duplicate_staged_source_hashes_in_batch(staged_sources)
    reject_committed_source_hash_matches(connection, staged_sources)
    return staged_sources


def reject_duplicate_staged_source_hashes_in_batch(
    hashed_sources: Sequence[HashedStagedSource],
) -> None:
    staged_entries_by_hash: dict[str, str] = {}

    for hashed_source in hashed_sources:
        staged_entry_id = hashed_source.staged_source.staging_entry_id
        source_hash = hashed_source.source_hash
        existing_staged_entry_id = staged_entries_by_hash.get(source_hash)

        if existing_staged_entry_id is not None:
            logger.warning("Rejected duplicate staged source hash in batch.")
            logger.debug(
                "Duplicate staged source hash in batch: first_staging_entry_id=%s "
                "duplicate_staging_entry_id=%s hash_prefix=%s",
                existing_staged_entry_id,
                staged_entry_id,
                get_hash_log_prefix(source_hash),
            )
            raise DuplicateStagedSourceError(
                "Staged source hash already exists in batch."
            )

        staged_entries_by_hash[source_hash] = staged_entry_id


def reject_committed_source_hash_matches(
    connection: sqlite3.Connection,
    hashed_sources: Sequence[HashedStagedSource],
) -> None:
    if not hashed_sources:
        return

    try:
        for hashed_source in hashed_sources:
            row = connection.execute(
                """
                SELECT source_id
                FROM committed_sources
                WHERE source_hash = ?
                ORDER BY book_number, source_id
                LIMIT 1
                """,
                (hashed_source.source_hash,),
            ).fetchone()

            if row is None:
                continue

            logger.warning("Rejected duplicate staged source hash in committed sources.")
            logger.debug(
                "Duplicate staged source hash in committed sources: "
                "staging_entry_id=%s committed_source_id=%s hash_prefix=%s",
                hashed_source.staged_source.staging_entry_id,
                row["source_id"],
                get_hash_log_prefix(hashed_source.source_hash),
            )
            raise DuplicateStagedSourceError(
                "Staged source hash already exists in committed sources."
            )
    except sqlite3.Error:
        logger.error("Failed to check duplicate staged source hashes.", exc_info=True)
        raise


def get_hash_log_prefix(source_hash: str) -> str:
    return source_hash[:HASH_LOG_PREFIX_LENGTH]
