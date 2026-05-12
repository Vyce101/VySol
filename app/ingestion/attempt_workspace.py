import atexit
from dataclasses import dataclass
from pathlib import Path
import tempfile

from app.logger import get_logger

logger = get_logger()


class IngestionAttemptWorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class TemporaryIngestionWorkspace:
    attempt_id: str
    workspace_path: Path


class IngestionAttemptWorkspaceRegistry:
    def __init__(self) -> None:
        self._temporary_directories: dict[str, tempfile.TemporaryDirectory] = {}
        self._current_attempt_id: str | None = None

    def __del__(self) -> None:
        self._cleanup_temporary_directories()

    def create_attempt_workspace(self, attempt_id: str) -> TemporaryIngestionWorkspace:
        try:
            temporary_directory = tempfile.TemporaryDirectory(prefix="vysol-ingestion-")
        except Exception as error:
            logger.error("Failed to create temporary ingestion workspace.")
            raise IngestionAttemptWorkspaceError(
                "Failed to create temporary ingestion workspace."
            ) from error

        self._temporary_directories[attempt_id] = temporary_directory
        self._current_attempt_id = attempt_id
        logger.info("Created temporary ingestion workspace: attempt_id=%s", attempt_id)
        return TemporaryIngestionWorkspace(
            attempt_id=attempt_id,
            workspace_path=Path(temporary_directory.name),
        )

    def _cleanup_temporary_directories(self) -> None:
        for temporary_directory in self._temporary_directories.values():
            temporary_directory.cleanup()

        self._temporary_directories.clear()
        self._current_attempt_id = None

    def remove_attempt_workspace(self, attempt_id: str) -> None:
        temporary_directory = self._temporary_directories.pop(attempt_id, None)
        if temporary_directory is not None:
            temporary_directory.cleanup()

        if self._current_attempt_id == attempt_id:
            self._current_attempt_id = None

    def get_attempt_workspace(
        self,
        attempt_id: str,
    ) -> TemporaryIngestionWorkspace | None:
        if attempt_id != self._current_attempt_id:
            return None

        temporary_directory = self._temporary_directories.get(attempt_id)
        if temporary_directory is None:
            return None

        return TemporaryIngestionWorkspace(
            attempt_id=attempt_id,
            workspace_path=Path(temporary_directory.name),
        )


_ingestion_attempt_workspace_registry = IngestionAttemptWorkspaceRegistry()


def get_ingestion_attempt_workspace_registry() -> IngestionAttemptWorkspaceRegistry:
    return _ingestion_attempt_workspace_registry


def create_attempt_workspace(attempt_id: str) -> TemporaryIngestionWorkspace:
    return _ingestion_attempt_workspace_registry.create_attempt_workspace(attempt_id)


def get_attempt_workspace(attempt_id: str) -> TemporaryIngestionWorkspace | None:
    return _ingestion_attempt_workspace_registry.get_attempt_workspace(attempt_id)


atexit.register(_ingestion_attempt_workspace_registry._cleanup_temporary_directories)
