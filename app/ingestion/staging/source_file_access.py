from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.ingestion.staging.source_staging_state import TemporarySourceStagingEntry
from app.logger import get_logger

logger = get_logger()

READ_PROBE_BYTE_COUNT = 1
FILE_ACCESS_REASON_MISSING = "missing"
FILE_ACCESS_REASON_NOT_FILE = "not_file"
FILE_ACCESS_REASON_UNREADABLE = "unreadable"

EXPECTED_READ_FAILURES = (
    FileNotFoundError,
    IsADirectoryError,
    PermissionError,
    OSError,
)


class StagedSourceFileAccessError(RuntimeError):
    pass


@dataclass(frozen=True)
class StagedSourceFileAccessFailure:
    staging_entry_id: str
    source_file_type: str
    reason: str


def validate_staged_source_file_access(
    entries: Sequence[TemporarySourceStagingEntry],
) -> tuple[TemporarySourceStagingEntry, ...]:
    staged_entries = tuple(entries)
    failures: list[StagedSourceFileAccessFailure] = []

    for entry in staged_entries:
        failure = get_staged_source_file_access_failure(entry)
        if failure is not None:
            failures.append(failure)

    if failures:
        reject_unavailable_staged_source_files(failures)

    return staged_entries


def get_staged_source_file_access_failure(
    entry: TemporarySourceStagingEntry,
) -> StagedSourceFileAccessFailure | None:
    source_file_path = Path(entry.source_file_path)

    try:
        if not source_file_path.exists():
            return make_file_access_failure(entry, FILE_ACCESS_REASON_MISSING)

        if not source_file_path.is_file():
            return make_file_access_failure(entry, FILE_ACCESS_REASON_NOT_FILE)

        with source_file_path.open("rb") as source_file:
            source_file.read(READ_PROBE_BYTE_COUNT)
    except EXPECTED_READ_FAILURES:
        return make_file_access_failure(entry, FILE_ACCESS_REASON_UNREADABLE)
    except Exception as error:
        logger.error(
            "Unexpected staged source file access failure: "
            "staging_entry_id=%s source_type=%s error_type=%s",
            entry.staging_entry_id,
            entry.source_file_type,
            type(error).__name__,
        )
        raise RuntimeError("Unexpected staged source file access failure.") from error

    return None


def make_file_access_failure(
    entry: TemporarySourceStagingEntry,
    reason: str,
) -> StagedSourceFileAccessFailure:
    return StagedSourceFileAccessFailure(
        staging_entry_id=entry.staging_entry_id,
        source_file_type=entry.source_file_type,
        reason=reason,
    )


def reject_unavailable_staged_source_files(
    failures: Sequence[StagedSourceFileAccessFailure],
) -> None:
    failure_summaries = tuple(
        (failure.staging_entry_id, failure.source_file_type, failure.reason)
        for failure in failures
    )
    logger.warning(
        "Unavailable staged source files block ingestion: count=%s failures=%s",
        len(failure_summaries),
        failure_summaries,
    )
    raise StagedSourceFileAccessError(
        "One or more staged source files are missing or unreadable."
    )
