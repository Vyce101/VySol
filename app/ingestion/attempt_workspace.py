import atexit
from dataclasses import dataclass
from pathlib import Path
import shutil
from uuid import uuid4

from app.logger import get_logger
from app.storage.paths import get_ingestion_workspaces_directory

logger = get_logger()

WORKSPACE_DIRECTORY_PREFIX = "workspace-"


class IngestionAttemptWorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class TemporaryIngestionWorkspace:
    attempt_id: str
    workspace_path: Path


class IngestionAttemptWorkspaceRegistry:
    def __init__(self, workspace_parent: Path | None = None) -> None:
        self._workspace_paths: dict[str, Path] = {}
        self._current_attempt_id: str | None = None
        self._workspace_parent = workspace_parent or get_ingestion_workspaces_directory()

    def __del__(self) -> None:
        self._cleanup_temporary_workspaces()

    def create_attempt_workspace(self, attempt_id: str) -> TemporaryIngestionWorkspace:
        workspace_path = self._workspace_parent / f"{WORKSPACE_DIRECTORY_PREFIX}{uuid4()}"

        try:
            self._workspace_parent.mkdir(parents=True, exist_ok=True)
            workspace_path.mkdir()
        except OSError as error:
            logger.error("Failed to create temporary ingestion workspace.")
            raise IngestionAttemptWorkspaceError(
                "Failed to create temporary ingestion workspace."
            ) from error

        self._workspace_paths[attempt_id] = workspace_path
        self._current_attempt_id = attempt_id
        logger.info("Created temporary ingestion workspace: attempt_id=%s", attempt_id)
        return TemporaryIngestionWorkspace(
            attempt_id=attempt_id,
            workspace_path=workspace_path,
        )

    def _cleanup_temporary_workspaces(self) -> None:
        for attempt_id in tuple(self._workspace_paths):
            self.remove_attempt_workspace(attempt_id)

        self._workspace_paths.clear()
        self._current_attempt_id = None

    def remove_attempt_workspace(self, attempt_id: str) -> None:
        workspace_path = self._workspace_paths.pop(attempt_id, None)
        if self._current_attempt_id == attempt_id:
            self._current_attempt_id = None

        if workspace_path is None:
            logger.debug(
                "Temporary ingestion workspace already cleaned: attempt_id=%s",
                attempt_id,
            )
            return

        clean_attempt_workspace_path(attempt_id, workspace_path)

    def get_attempt_workspace(
        self,
        attempt_id: str,
    ) -> TemporaryIngestionWorkspace | None:
        if attempt_id != self._current_attempt_id:
            return None

        workspace_path = self._workspace_paths.get(attempt_id)
        if workspace_path is None:
            return None

        return TemporaryIngestionWorkspace(
            attempt_id=attempt_id,
            workspace_path=workspace_path,
        )


def clean_attempt_workspace_path(attempt_id: str, workspace_path: Path) -> bool:
    if not workspace_path.exists():
        logger.debug(
            "Temporary ingestion workspace already cleaned: attempt_id=%s",
            attempt_id,
        )
        return False

    try:
        shutil.rmtree(workspace_path)
    except OSError as error:
        logger.error(
            "Failed to clean temporary ingestion workspace: "
            "attempt_id=%s error_type=%s",
            attempt_id,
            type(error).__name__,
            exc_info=True,
        )
        return False

    logger.info("Cleaned temporary ingestion workspace: attempt_id=%s", attempt_id)
    return True


def cleanup_abandoned_attempt_workspaces(workspace_parent: Path | None = None) -> int:
    parent = workspace_parent or get_ingestion_workspaces_directory()
    if not parent.exists():
        logger.debug("No abandoned temporary ingestion workspaces found.")
        return 0

    try:
        abandoned_workspaces = tuple(
            path
            for path in parent.iterdir()
            if path.is_dir() and path.name.startswith(WORKSPACE_DIRECTORY_PREFIX)
        )
    except OSError as error:
        logger.error(
            "Failed to inspect abandoned temporary ingestion workspaces: error_type=%s",
            type(error).__name__,
            exc_info=True,
        )
        return 0

    cleanup_count = sum(
        1
        for workspace_path in abandoned_workspaces
        if clean_attempt_workspace_path("startup", workspace_path)
    )
    logger.info(
        "Cleaned abandoned temporary ingestion workspaces: count=%s",
        cleanup_count,
    )
    return cleanup_count


_ingestion_attempt_workspace_registry = IngestionAttemptWorkspaceRegistry()


def get_ingestion_attempt_workspace_registry() -> IngestionAttemptWorkspaceRegistry:
    return _ingestion_attempt_workspace_registry


def create_attempt_workspace(attempt_id: str) -> TemporaryIngestionWorkspace:
    return _ingestion_attempt_workspace_registry.create_attempt_workspace(attempt_id)


def get_attempt_workspace(attempt_id: str) -> TemporaryIngestionWorkspace | None:
    return _ingestion_attempt_workspace_registry.get_attempt_workspace(attempt_id)


atexit.register(_ingestion_attempt_workspace_registry._cleanup_temporary_workspaces)
