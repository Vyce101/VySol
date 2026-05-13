from app.draft_worlds.registry import (
    DraftWorldRegistry,
    get_draft_world_registry,
)
from app.ingestion.active_staged_batch import (
    ActiveStagedBatchRegistry,
    StagedBatchAttemptKind,
    get_active_staged_batch_registry,
)
from app.ingestion.attempt_state import (
    IngestionAttemptState,
    IngestionAttemptStateRegistry,
    IngestionAttemptStatus,
    get_ingestion_attempt_state_registry,
)
from app.ingestion.staging.source_staging_state import (
    SourceStagingStateRegistry,
    get_source_staging_state_registry,
)
from app.logger import get_logger

logger = get_logger()

APP_CLOSE_CANCELLABLE_STATUSES = {
    IngestionAttemptStatus.RUNNING,
    IngestionAttemptStatus.STOPPING,
    IngestionAttemptStatus.PAUSED,
}


class AppCloseAttemptCancellationCoordinator:
    def __init__(
        self,
        attempt_state_registry: IngestionAttemptStateRegistry | None = None,
        active_batch_registry: ActiveStagedBatchRegistry | None = None,
        source_staging_registry: SourceStagingStateRegistry | None = None,
        draft_world_registry: DraftWorldRegistry | None = None,
    ) -> None:
        self._attempt_state_registry = (
            attempt_state_registry or get_ingestion_attempt_state_registry()
        )
        self._active_batch_registry = (
            active_batch_registry or get_active_staged_batch_registry()
        )
        self._source_staging_registry = (
            source_staging_registry or get_source_staging_state_registry()
        )
        self._draft_world_registry = draft_world_registry or get_draft_world_registry()

    def cancel_for_app_close(self) -> IngestionAttemptState:
        state = self._attempt_state_registry.get_state()
        if state.status not in APP_CLOSE_CANCELLABLE_STATUSES:
            return state

        active_attempt = self._active_batch_registry.get_current_staged_batch_attempt()
        cancelled_state = self._attempt_state_registry.cancel_for_app_close()

        if active_attempt is None:
            logger.info(
                "Cancelled ingestion attempt for app close: "
                "attempt_id=%s attempt_kind=%s staging_context_id=%s source_count=%s",
                cancelled_state.attempt_id,
                None,
                None,
                0,
            )
            return cancelled_state

        self._source_staging_registry.discard_staging_context(
            active_attempt.staging_context_id,
        )
        if active_attempt.attempt_kind == StagedBatchAttemptKind.NEW_WORLD:
            self._draft_world_registry.discard_draft_world(active_attempt.target_id)

        self._active_batch_registry.clear_current_staged_batch_attempt()
        logger.info(
            "Cancelled ingestion attempt for app close: "
            "attempt_id=%s attempt_kind=%s staging_context_id=%s source_count=%s",
            cancelled_state.attempt_id,
            active_attempt.attempt_kind,
            active_attempt.staging_context_id,
            len(active_attempt.staging_entry_ids),
        )
        return cancelled_state


_app_close_attempt_cancellation_coordinator = AppCloseAttemptCancellationCoordinator()


def cancel_active_attempt_for_app_close() -> IngestionAttemptState:
    return _app_close_attempt_cancellation_coordinator.cancel_for_app_close()
