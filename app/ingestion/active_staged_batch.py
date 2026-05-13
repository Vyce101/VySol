from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import NoReturn

from app.ingestion.attempt_state import (
    IngestionAttemptState,
    IngestionAttemptStatus,
    get_attempt_state,
)
from app.logger import get_logger

logger = get_logger()


class StagedBatchAttemptKind(StrEnum):
    NEW_WORLD = "new_world"
    EXISTING_WORLD = "existing_world"


class RunningStagedBatchSourceAddError(RuntimeError):
    pass


class ActiveStagedBatchAttemptError(ValueError):
    pass


@dataclass(frozen=True)
class StagedBatchAttemptTarget:
    attempt_kind: StagedBatchAttemptKind
    target_id: str


@dataclass(frozen=True)
class ActiveStagedBatchAttempt:
    attempt_state: IngestionAttemptState
    staging_context_id: str
    attempt_kind: StagedBatchAttemptKind
    target_id: str
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
        attempt_target: StagedBatchAttemptTarget,
        staging_entry_ids: Sequence[str],
    ) -> ActiveStagedBatchAttempt:
        validated_target = validate_staged_batch_attempt_target(attempt_target)
        active_attempt = ActiveStagedBatchAttempt(
            attempt_state=attempt_state,
            staging_context_id=staging_context_id,
            attempt_kind=validated_target.attempt_kind,
            target_id=validated_target.target_id,
            staging_entry_ids=tuple(staging_entry_ids),
        )
        self._active_attempt = active_attempt
        return active_attempt

    def get_current_staged_batch_attempt(self) -> ActiveStagedBatchAttempt | None:
        if self._active_attempt is None:
            return None

        current_state = self._attempt_state_reader()
        if current_state.attempt_id != self._active_attempt.attempt_state.attempt_id:
            self._active_attempt = None
            return None

        if current_state.status in {
            IngestionAttemptStatus.IDLE,
            IngestionAttemptStatus.COMPLETE,
        }:
            self._active_attempt = None
            return None

        return self._active_attempt

    def get_active_staged_batch_attempt(self) -> ActiveStagedBatchAttempt | None:
        current_attempt = self.get_current_staged_batch_attempt()
        if current_attempt is None:
            return None
        current_state = self._attempt_state_reader()
        if current_state.status != IngestionAttemptStatus.RUNNING:
            return None

        return current_attempt

    def is_staging_context_locked_for_running_attempt(
        self,
        staging_context_id: str,
    ) -> bool:
        active_attempt = self.get_active_staged_batch_attempt()
        return (
            active_attempt is not None
            and active_attempt.staging_context_id == staging_context_id
        )

    def clear_current_staged_batch_attempt(self) -> ActiveStagedBatchAttempt | None:
        active_attempt = self._active_attempt
        self._active_attempt = None
        return active_attempt


def validate_staged_batch_attempt_target(
    attempt_target: StagedBatchAttemptTarget,
) -> StagedBatchAttemptTarget:
    if type(attempt_target) is not StagedBatchAttemptTarget:
        reject_staged_batch_attempt_target("Staged batch attempt target is invalid.")

    if type(attempt_target.attempt_kind) is not StagedBatchAttemptKind:
        reject_staged_batch_attempt_target("Staged batch attempt kind is invalid.")

    if (
        type(attempt_target.target_id) is not str
        or not attempt_target.target_id.strip()
    ):
        reject_staged_batch_attempt_target(
            "Staged batch attempt target ID is required."
        )

    return attempt_target


def reject_staged_batch_attempt_target(message: str) -> NoReturn:
    logger.warning("Invalid staged batch attempt target: %s", message)
    raise ActiveStagedBatchAttemptError(message)


_active_staged_batch_registry = ActiveStagedBatchRegistry()


def get_active_staged_batch_registry() -> ActiveStagedBatchRegistry:
    return _active_staged_batch_registry


def get_active_staged_batch_attempt() -> ActiveStagedBatchAttempt | None:
    return _active_staged_batch_registry.get_active_staged_batch_attempt()


def get_current_staged_batch_attempt() -> ActiveStagedBatchAttempt | None:
    return _active_staged_batch_registry.get_current_staged_batch_attempt()


def is_staging_context_locked_for_running_attempt(staging_context_id: str) -> bool:
    return _active_staged_batch_registry.is_staging_context_locked_for_running_attempt(
        staging_context_id,
    )


def clear_current_staged_batch_attempt() -> ActiveStagedBatchAttempt | None:
    return _active_staged_batch_registry.clear_current_staged_batch_attempt()
