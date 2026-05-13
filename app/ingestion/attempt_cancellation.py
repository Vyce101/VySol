from dataclasses import dataclass


class IngestionAttemptCancellationError(RuntimeError):
    pass


@dataclass
class IngestionAttemptCancellationRegistry:
    _cancellation_flags: dict[str, bool]

    def __init__(self) -> None:
        self._cancellation_flags = {}

    def initialize_attempt(self, attempt_id: str) -> None:
        self._cancellation_flags[validate_attempt_id(attempt_id)] = False

    def request_cancellation(self, attempt_id: str) -> None:
        self._cancellation_flags[validate_attempt_id(attempt_id)] = True

    def is_cancellation_requested(self, attempt_id: str) -> bool:
        return self._cancellation_flags.get(validate_attempt_id(attempt_id), False)

    def clear_attempt(self, attempt_id: str) -> None:
        self._cancellation_flags.pop(validate_attempt_id(attempt_id), None)


def validate_attempt_id(attempt_id: str) -> str:
    if type(attempt_id) is str and attempt_id.strip():
        return attempt_id

    raise IngestionAttemptCancellationError("Ingestion attempt ID is required.")


_ingestion_attempt_cancellation_registry = IngestionAttemptCancellationRegistry()


def get_ingestion_attempt_cancellation_registry() -> IngestionAttemptCancellationRegistry:
    return _ingestion_attempt_cancellation_registry


def initialize_attempt_cancellation(attempt_id: str) -> None:
    _ingestion_attempt_cancellation_registry.initialize_attempt(attempt_id)


def request_attempt_cancellation(attempt_id: str) -> None:
    _ingestion_attempt_cancellation_registry.request_cancellation(attempt_id)


def is_cancellation_requested(attempt_id: str) -> bool:
    return _ingestion_attempt_cancellation_registry.is_cancellation_requested(
        attempt_id,
    )


def clear_attempt_cancellation(attempt_id: str) -> None:
    _ingestion_attempt_cancellation_registry.clear_attempt(attempt_id)
