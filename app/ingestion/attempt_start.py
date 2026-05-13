from collections.abc import Sequence
from dataclasses import dataclass

from app.ingestion.active_staged_batch import (
    ActiveStagedBatchAttemptError,
    ActiveStagedBatchAttempt,
    ActiveStagedBatchRegistry,
    StagedBatchAttemptTarget,
    get_active_staged_batch_registry,
    validate_staged_batch_attempt_target,
)
from app.ingestion.attempt_state import (
    IngestionAttemptStateRegistry,
    IngestionAttemptStatus,
    InvalidIngestionAttemptTransitionError,
    get_ingestion_attempt_state_registry,
)
from app.ingestion.staging.source_staging_state import (
    SourceStagingState,
    SourceStagingStateRegistry,
    TemporarySourceStagingEntry,
    get_source_staging_state_registry,
)
from app.logger import get_logger

logger = get_logger()


class StagedBatchStartValidationError(ValueError):
    def __init__(
        self,
        message: str,
        invalid_staged_sources: Sequence["InvalidStagedSourceSummary"] = (),
    ) -> None:
        super().__init__(message)
        self.invalid_staged_sources = tuple(invalid_staged_sources)


class DuplicateIngestionAttemptStartError(RuntimeError):
    pass


class IngestionAttemptStartOrchestrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class InvalidStagedSourceSummary:
    staging_entry_id: str
    source_file_type: str
    error_message: str | None


class IngestionAttemptStartRegistry:
    def __init__(
        self,
        attempt_state_registry: IngestionAttemptStateRegistry | None = None,
        source_staging_registry: SourceStagingStateRegistry | None = None,
        active_batch_registry: ActiveStagedBatchRegistry | None = None,
    ) -> None:
        self._attempt_state_registry = (
            attempt_state_registry or get_ingestion_attempt_state_registry()
        )
        self._source_staging_registry = (
            source_staging_registry or get_source_staging_state_registry()
        )
        self._active_batch_registry = (
            active_batch_registry or get_active_staged_batch_registry()
        )

    def start_staged_batch_attempt(
        self,
        staging_context_id: str,
        attempt_target: StagedBatchAttemptTarget,
    ) -> ActiveStagedBatchAttempt:
        try:
            validated_attempt_target = validate_staged_batch_attempt_target(
                attempt_target,
            )
            self._reject_duplicate_running_start(staging_context_id)
            staging_state = self._get_valid_staging_state(staging_context_id)
            attempt_state = self._attempt_state_registry.start_attempt()
            active_attempt = (
                self._active_batch_registry.record_active_staged_batch_attempt(
                    attempt_state=attempt_state,
                    staging_context_id=staging_state.staging_context_id,
                    attempt_target=validated_attempt_target,
                    staging_entry_ids=(
                        entry.staging_entry_id for entry in staging_state.entries
                    ),
                )
            )
        except (
            ActiveStagedBatchAttemptError,
            DuplicateIngestionAttemptStartError,
            StagedBatchStartValidationError,
            InvalidIngestionAttemptTransitionError,
        ):
            raise
        except Exception as error:
            logger.error(
                "Failed to start staged batch ingestion attempt: "
                "staging_context_id=%s error_type=%s",
                staging_context_id,
                type(error).__name__,
                exc_info=True,
            )
            raise IngestionAttemptStartOrchestrationError(
                "Failed to start staged batch ingestion attempt."
            ) from error

        logger.info(
            "Started staged batch ingestion attempt: "
            "attempt_id=%s staging_context_id=%s source_count=%s",
            active_attempt.attempt_state.attempt_id,
            active_attempt.staging_context_id,
            len(active_attempt.staging_entry_ids),
        )
        return active_attempt

    def _reject_duplicate_running_start(self, staging_context_id: str) -> None:
        attempt_state = self._attempt_state_registry.get_state()
        if attempt_state.status != IngestionAttemptStatus.RUNNING:
            return

        logger.warning(
            "Rejected duplicate staged batch start while attempt is running: "
            "attempt_id=%s staging_context_id=%s",
            attempt_state.attempt_id,
            staging_context_id,
        )
        raise DuplicateIngestionAttemptStartError(
            "An ingestion attempt is already running."
        )

    def _get_valid_staging_state(self, staging_context_id: str) -> SourceStagingState:
        staging_state = self._source_staging_registry.get_staging_state(
            staging_context_id,
        )
        if staging_state is None:
            self._reject_invalid_start(
                "Staging context is missing.",
                staging_context_id,
                "missing_staging_context",
            )

        if not staging_state.entries:
            self._reject_invalid_start(
                "Staging context has no staged sources.",
                staging_context_id,
                "empty_staging_list",
            )

        invalid_entries = get_invalid_staged_source_summaries(staging_state.entries)
        if invalid_entries:
            logger.warning(
                "Rejected staged batch start with invalid staged sources: "
                "staging_context_id=%s count=%s invalid_sources=%s",
                staging_context_id,
                len(invalid_entries),
                tuple(
                    (entry.staging_entry_id, entry.source_file_type)
                    for entry in invalid_entries
                ),
            )
            raise StagedBatchStartValidationError(
                "One or more staged sources are invalid.",
                invalid_entries,
            )

        return staging_state

    def _reject_invalid_start(
        self,
        message: str,
        staging_context_id: str,
        reason: str,
    ) -> None:
        logger.warning(
            "Rejected staged batch start: staging_context_id=%s reason=%s",
            staging_context_id,
            reason,
        )
        raise StagedBatchStartValidationError(message)


def get_invalid_staged_source_summaries(
    entries: Sequence[TemporarySourceStagingEntry],
) -> tuple[InvalidStagedSourceSummary, ...]:
    return tuple(
        InvalidStagedSourceSummary(
            staging_entry_id=entry.staging_entry_id,
            source_file_type=entry.source_file_type,
            error_message=entry.error_message,
        )
        for entry in entries
        if not entry.is_valid
    )


_ingestion_attempt_start_registry = IngestionAttemptStartRegistry()


def start_staged_batch_attempt(
    staging_context_id: str,
    attempt_target: StagedBatchAttemptTarget,
) -> ActiveStagedBatchAttempt:
    return _ingestion_attempt_start_registry.start_staged_batch_attempt(
        staging_context_id,
        attempt_target,
    )
