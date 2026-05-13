from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.ingestion.attempt_state import (
    IngestionAttemptState,
    IngestionAttemptStatus,
    get_attempt_state,
)


class RunningStagedBatchSourceAddError(RuntimeError):
    pass


@dataclass(frozen=True)
class ActiveStagedBatchAttempt:
    attempt_state: IngestionAttemptState
    staging_context_id: str
    staging_entry_ids: tuple[str, ...]


class ActiveStagedBatchRegistry:
    def __init__(
        self,
        attempt_state_reader: Callable[[], IngestionAttemptState] | None = None,
    ) -> None:
        self._active_attempt: ActiveStagedBatchAttempt | None = None
        self._attempt_state_reader = attempt_state_reader or get_attempt_state

    def record_active_staged_batch_attempt(
        self,
        attempt_state: IngestionAttemptState,
        staging_context_id: str,
        staging_entry_ids: Sequence[str],
    ) -> ActiveStagedBatchAttempt:
        active_attempt = ActiveStagedBatchAttempt(
            attempt_state=attempt_state,
            staging_context_id=staging_context_id,
            staging_entry_ids=tuple(staging_entry_ids),
        )
        self._active_attempt = active_attempt
        return active_attempt

    def get_active_staged_batch_attempt(self) -> ActiveStagedBatchAttempt | None:
        if self._active_attempt is None:
            return None

        current_state = self._attempt_state_reader()
        if current_state.status != IngestionAttemptStatus.RUNNING:
            self._active_attempt = None
            return None

        if current_state.attempt_id != self._active_attempt.attempt_state.attempt_id:
            self._active_attempt = None
            return None

        return self._active_attempt

    def is_staging_context_locked_for_running_attempt(
        self,
        staging_context_id: str,
    ) -> bool:
        active_attempt = self.get_active_staged_batch_attempt()
        return (
            active_attempt is not None
            and active_attempt.staging_context_id == staging_context_id
        )


_active_staged_batch_registry = ActiveStagedBatchRegistry()


def get_active_staged_batch_registry() -> ActiveStagedBatchRegistry:
    return _active_staged_batch_registry


def get_active_staged_batch_attempt() -> ActiveStagedBatchAttempt | None:
    return _active_staged_batch_registry.get_active_staged_batch_attempt()


def is_staging_context_locked_for_running_attempt(staging_context_id: str) -> bool:
    return _active_staged_batch_registry.is_staging_context_locked_for_running_attempt(
        staging_context_id,
    )
