from dataclasses import dataclass
from enum import StrEnum
from typing import NoReturn
from uuid import uuid4

from app.ingestion.attempt_workspace import (
    IngestionAttemptWorkspaceError,
    IngestionAttemptWorkspaceRegistry,
    TemporaryIngestionWorkspace,
    get_ingestion_attempt_workspace_registry,
)
from app.ingestion.attempt_cancellation import (
    IngestionAttemptCancellationError,
    IngestionAttemptCancellationRegistry,
    get_ingestion_attempt_cancellation_registry,
)
from app.logger import get_logger

logger = get_logger()


class IngestionAttemptStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    STOPPING = "stopping"
    PAUSED = "paused"
    COMPLETE = "complete"


class IngestionAttemptPhase(StrEnum):
    NOT_STARTED = "not_started"
    PREFLIGHT = "preflight"
    PARSING = "parsing"
    SPLITTING = "splitting"
    ATOMIC_TEXT_COMMIT = "atomic_text_commit"
    TEXT_COMMITTED = "text_committed"


class IngestionAttemptStateError(ValueError):
    pass


class StaleIngestionAttemptResultError(IngestionAttemptStateError):
    pass


class InvalidIngestionAttemptTransitionError(IngestionAttemptStateError):
    pass


@dataclass(frozen=True)
class IngestionAttemptState:
    status: IngestionAttemptStatus
    attempt_id: str | None
    staged_work_remaining: bool
    phase: IngestionAttemptPhase = IngestionAttemptPhase.NOT_STARTED


class IngestionAttemptStateRegistry:
    def __init__(
        self,
        workspace_registry: IngestionAttemptWorkspaceRegistry | None = None,
        cancellation_registry: IngestionAttemptCancellationRegistry | None = None,
    ) -> None:
        self._state = build_idle_state()
        self._workspace_registry = workspace_registry or IngestionAttemptWorkspaceRegistry()
        self._cancellation_registry = (
            cancellation_registry or IngestionAttemptCancellationRegistry()
        )

    def get_state(self) -> IngestionAttemptState:
        return self._state

    def get_attempt_workspace(
        self,
        attempt_id: str,
    ) -> TemporaryIngestionWorkspace | None:
        return self._workspace_registry.get_attempt_workspace(attempt_id)

    def start_attempt(self) -> IngestionAttemptState:
        if self._state.status not in {
            IngestionAttemptStatus.IDLE,
            IngestionAttemptStatus.COMPLETE,
        }:
            reject_invalid_transition("Cannot start ingestion from current state.")

        attempt_id = str(uuid4())
        self._workspace_registry.create_attempt_workspace(attempt_id)
        try:
            self._cancellation_registry.initialize_attempt(attempt_id)
            return self._set_state(
                IngestionAttemptState(
                    status=IngestionAttemptStatus.RUNNING,
                    attempt_id=attempt_id,
                    staged_work_remaining=True,
                    phase=IngestionAttemptPhase.PREFLIGHT,
                )
            )
        except Exception:
            self._cancellation_registry.clear_attempt(attempt_id)
            self._workspace_registry.remove_attempt_workspace(attempt_id)
            raise

    def request_stop(self) -> IngestionAttemptState:
        if self._state.status == IngestionAttemptStatus.STOPPING:
            logger.warning(
                "Ignored repeated ingestion pause request: attempt_id=%s",
                self._state.attempt_id,
            )
            return self._state

        if self._state.status != IngestionAttemptStatus.RUNNING:
            reject_invalid_transition("Cannot pause ingestion from current state.")

        if self._state.attempt_id is None:
            reject_invalid_transition("Cannot pause ingestion without an attempt ID.")

        try:
            self._cancellation_registry.request_cancellation(self._state.attempt_id)
        except Exception as error:
            logger.error(
                "Failed to set ingestion attempt cancellation flag: "
                "attempt_id=%s error_type=%s",
                self._state.attempt_id,
                type(error).__name__,
                exc_info=True,
            )
            raise IngestionAttemptCancellationError(
                "Failed to set ingestion attempt cancellation flag."
            ) from error

        logger.info(
            "Ingestion pause requested: attempt_id=%s",
            self._state.attempt_id,
        )

        return self._set_state(
            IngestionAttemptState(
                status=IngestionAttemptStatus.STOPPING,
                attempt_id=self._state.attempt_id,
                staged_work_remaining=self._state.staged_work_remaining,
                phase=self._state.phase,
            )
        )

    def finish_cancellation(
        self,
        attempt_id: str,
        staged_work_remaining: bool,
    ) -> IngestionAttemptState:
        self._validate_current_attempt_result(
            attempt_id,
            IngestionAttemptStatus.STOPPING,
        )

        logger.info(
            "Ingestion cancellation completed: attempt_id=%s staged_work_remaining=%s",
            attempt_id,
            staged_work_remaining,
        )

        if staged_work_remaining:
            return self._set_state(
                IngestionAttemptState(
                    status=IngestionAttemptStatus.PAUSED,
                    attempt_id=self._state.attempt_id,
                    staged_work_remaining=True,
                    phase=self._state.phase,
                )
            )

        state = self._set_state(build_idle_state())
        self._cancellation_registry.clear_attempt(attempt_id)
        self._workspace_registry.remove_attempt_workspace(attempt_id)
        return state

    def resume_attempt(self) -> IngestionAttemptState:
        if self._state.status != IngestionAttemptStatus.PAUSED:
            reject_invalid_transition("Cannot resume ingestion from current state.")

        if not self._state.staged_work_remaining:
            reject_invalid_transition("Cannot resume ingestion without staged work.")

        if self._state.attempt_id is None:
            reject_invalid_transition("Cannot resume ingestion without an attempt ID.")

        if self.get_attempt_workspace(self._state.attempt_id) is None:
            logger.error("Missing temporary ingestion workspace for paused attempt.")
            raise IngestionAttemptWorkspaceError(
                "Temporary ingestion workspace is missing."
            )

        self._cancellation_registry.initialize_attempt(self._state.attempt_id)
        return self._set_state(
            IngestionAttemptState(
                status=IngestionAttemptStatus.RUNNING,
                attempt_id=self._state.attempt_id,
                staged_work_remaining=True,
                phase=self._state.phase,
            )
        )

    def update_attempt_phase(
        self,
        attempt_id: str,
        phase: IngestionAttemptPhase,
    ) -> IngestionAttemptState:
        self._validate_current_attempt_result(
            attempt_id,
            IngestionAttemptStatus.RUNNING,
        )

        if type(phase) is not IngestionAttemptPhase:
            reject_invalid_transition("Ingestion attempt phase is invalid.")

        return self._set_state(
            IngestionAttemptState(
                status=self._state.status,
                attempt_id=self._state.attempt_id,
                staged_work_remaining=self._state.staged_work_remaining,
                phase=phase,
            )
        )

    def complete_attempt(self, attempt_id: str) -> IngestionAttemptState:
        if (
            self._state.attempt_id == attempt_id
            and self._state.status
            in {IngestionAttemptStatus.STOPPING, IngestionAttemptStatus.PAUSED}
        ):
            reject_late_cancelled_result(attempt_id, self._state.status)

        self._validate_current_attempt_result(
            attempt_id,
            IngestionAttemptStatus.RUNNING,
        )

        state = self._set_state(
            IngestionAttemptState(
                status=IngestionAttemptStatus.COMPLETE,
                attempt_id=self._state.attempt_id,
                staged_work_remaining=False,
                phase=IngestionAttemptPhase.NOT_STARTED,
            )
        )
        self._workspace_registry.remove_attempt_workspace(attempt_id)
        self._cancellation_registry.clear_attempt(attempt_id)
        return state

    def cancel_for_app_close(self) -> IngestionAttemptState:
        if self._state.status not in {
            IngestionAttemptStatus.RUNNING,
            IngestionAttemptStatus.STOPPING,
            IngestionAttemptStatus.PAUSED,
        }:
            return self._state

        if self._state.attempt_id is None:
            reject_invalid_transition(
                "Cannot close-cancel ingestion without an attempt ID."
            )

        attempt_id = self._state.attempt_id
        previous_status = self._state.status
        try:
            if not self._cancellation_registry.is_cancellation_requested(attempt_id):
                self._cancellation_registry.request_cancellation(attempt_id)
        except Exception as error:
            logger.error(
                "Failed to set app-close ingestion cancellation flag: "
                "attempt_id=%s error_type=%s",
                attempt_id,
                type(error).__name__,
                exc_info=True,
            )
            raise IngestionAttemptCancellationError(
                "Failed to set app-close ingestion cancellation flag."
            ) from error

        self._workspace_registry.abandon_attempt_workspace(attempt_id)
        logger.info(
            "Ingestion attempt cancelled for app close: "
            "attempt_id=%s previous_status=%s",
            attempt_id,
            previous_status,
        )
        return self._set_state(
            IngestionAttemptState(
                status=IngestionAttemptStatus.STOPPING,
                attempt_id=attempt_id,
                staged_work_remaining=False,
                phase=self._state.phase,
            )
        )

    def is_cancellation_requested(self, attempt_id: str) -> bool:
        return self._cancellation_registry.is_cancellation_requested(attempt_id)

    def _validate_current_attempt_result(
        self,
        attempt_id: str,
        required_status: IngestionAttemptStatus,
    ) -> None:
        if self._state.attempt_id != attempt_id:
            reject_stale_result()

        if self._state.status != required_status:
            reject_invalid_transition("Attempt result does not match current state.")

    def _set_state(self, updated_state: IngestionAttemptState) -> IngestionAttemptState:
        try:
            previous_status = self._state.status
            self._state = validate_attempt_state(updated_state)
        except Exception as error:
            logger.error("Unexpected ingestion attempt state failure.", exc_info=True)
            raise RuntimeError("Unexpected ingestion attempt state failure.") from error

        logger.info(
            "Ingestion attempt state changed: from_status=%s to_status=%s attempt_id=%s",
            previous_status,
            self._state.status,
            self._state.attempt_id,
        )
        return self._state


def build_idle_state() -> IngestionAttemptState:
    return IngestionAttemptState(
        status=IngestionAttemptStatus.IDLE,
        attempt_id=None,
        staged_work_remaining=False,
        phase=IngestionAttemptPhase.NOT_STARTED,
    )


def validate_attempt_state(state: IngestionAttemptState) -> IngestionAttemptState:
    if type(state) is not IngestionAttemptState:
        raise IngestionAttemptStateError("Ingestion attempt state is invalid.")

    if type(state.status) is not IngestionAttemptStatus:
        raise IngestionAttemptStateError("Ingestion attempt status is invalid.")

    if type(state.phase) is not IngestionAttemptPhase:
        raise IngestionAttemptStateError("Ingestion attempt phase is invalid.")

    if state.status == IngestionAttemptStatus.IDLE and state.attempt_id is not None:
        raise IngestionAttemptStateError("Idle ingestion attempts cannot have an ID.")

    if state.status == IngestionAttemptStatus.IDLE and state.staged_work_remaining:
        raise IngestionAttemptStateError("Idle ingestion attempts cannot have staged work.")

    if state.status != IngestionAttemptStatus.IDLE and not state.attempt_id:
        raise IngestionAttemptStateError("Active ingestion attempts require an ID.")

    if state.status == IngestionAttemptStatus.PAUSED and not state.staged_work_remaining:
        raise IngestionAttemptStateError("Paused ingestion attempts require staged work.")

    if state.status == IngestionAttemptStatus.COMPLETE and state.staged_work_remaining:
        raise IngestionAttemptStateError("Complete ingestion attempts cannot have staged work.")

    if state.status in {
        IngestionAttemptStatus.IDLE,
        IngestionAttemptStatus.COMPLETE,
    } and state.phase != IngestionAttemptPhase.NOT_STARTED:
        raise IngestionAttemptStateError("Inactive ingestion attempts cannot have a phase.")

    return state


def reject_stale_result() -> NoReturn:
    logger.warning("Rejected stale ingestion attempt result.")
    raise StaleIngestionAttemptResultError("Rejected stale ingestion attempt result.")


def reject_late_cancelled_result(
    attempt_id: str,
    status: IngestionAttemptStatus,
) -> NoReturn:
    logger.warning(
        "Rejected late ingestion attempt result after cancellation: "
        "attempt_id=%s status=%s",
        attempt_id,
        status,
    )
    raise InvalidIngestionAttemptTransitionError(
        "Cancelled ingestion attempts cannot complete."
    )


def reject_invalid_transition(message: str) -> NoReturn:
    logger.warning("Invalid ingestion attempt state transition: %s", message)
    raise InvalidIngestionAttemptTransitionError(message)


_ingestion_attempt_workspace_registry = get_ingestion_attempt_workspace_registry()
_ingestion_attempt_cancellation_registry = (
    get_ingestion_attempt_cancellation_registry()
)
_ingestion_attempt_state_registry = IngestionAttemptStateRegistry(
    _ingestion_attempt_workspace_registry,
    _ingestion_attempt_cancellation_registry,
)


def get_ingestion_attempt_state_registry() -> IngestionAttemptStateRegistry:
    return _ingestion_attempt_state_registry


def get_attempt_state() -> IngestionAttemptState:
    return _ingestion_attempt_state_registry.get_state()


def get_attempt_workspace(attempt_id: str) -> TemporaryIngestionWorkspace | None:
    return _ingestion_attempt_workspace_registry.get_attempt_workspace(attempt_id)


def start_attempt() -> IngestionAttemptState:
    return _ingestion_attempt_state_registry.start_attempt()


def request_stop() -> IngestionAttemptState:
    return _ingestion_attempt_state_registry.request_stop()


def finish_cancellation(
    attempt_id: str,
    staged_work_remaining: bool,
) -> IngestionAttemptState:
    return _ingestion_attempt_state_registry.finish_cancellation(
        attempt_id,
        staged_work_remaining,
    )


def resume_attempt() -> IngestionAttemptState:
    return _ingestion_attempt_state_registry.resume_attempt()


def update_attempt_phase(
    attempt_id: str,
    phase: IngestionAttemptPhase,
) -> IngestionAttemptState:
    return _ingestion_attempt_state_registry.update_attempt_phase(attempt_id, phase)


def complete_attempt(attempt_id: str) -> IngestionAttemptState:
    return _ingestion_attempt_state_registry.complete_attempt(attempt_id)


def is_cancellation_requested(attempt_id: str) -> bool:
    return _ingestion_attempt_state_registry.is_cancellation_requested(attempt_id)


def cancel_attempt_for_app_close() -> IngestionAttemptState:
    return _ingestion_attempt_state_registry.cancel_for_app_close()
