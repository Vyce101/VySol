import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ingestion.attempt_state import (
    IngestionAttemptCancellationError,
    IngestionAttemptCancellationRegistry,
    IngestionAttemptState,
    IngestionAttemptStateRegistry,
    IngestionAttemptStatus,
    IngestionAttemptWorkspaceError,
    InvalidIngestionAttemptTransitionError,
    StaleIngestionAttemptResultError,
)
from app.ingestion.attempt_workspace import (
    IngestionAttemptWorkspaceRegistry,
    WORKSPACE_DIRECTORY_PREFIX,
    cleanup_abandoned_attempt_workspaces,
)
from app.storage.database import bootstrap_global_database, close_global_connection
from app.storage.migrations import get_schema_version
from app.storage.paths import get_worlds_directory
from app.storage.world_migrations import apply_world_migrations, get_world_schema_version


class IngestionAttemptStateTests(unittest.TestCase):
    def tearDown(self) -> None:
        close_global_connection()

    def test_initial_state_is_idle_without_attempt_id(self) -> None:
        registry = IngestionAttemptStateRegistry()

        self.assertEqual(
            registry.get_state(),
            IngestionAttemptState(
                status=IngestionAttemptStatus.IDLE,
                attempt_id=None,
                staged_work_remaining=False,
            ),
        )

    def test_start_attempt_creates_running_state_with_attempt_id(self) -> None:
        registry = IngestionAttemptStateRegistry()

        with (
            patch("app.ingestion.attempt_state.uuid4", return_value="attempt-1"),
            patch("app.ingestion.attempt_state.logger") as logger,
        ):
            state = registry.start_attempt()

        self.assertEqual(
            state,
            IngestionAttemptState(
                status=IngestionAttemptStatus.RUNNING,
                attempt_id="attempt-1",
                staged_work_remaining=True,
            ),
        )
        workspace = registry.get_attempt_workspace("attempt-1")

        self.assertIsNotNone(workspace)
        self.assertEqual(workspace.attempt_id, "attempt-1")
        self.assertTrue(workspace.workspace_path.exists())
        logger.info.assert_called_once_with(
            "Ingestion attempt state changed: from_status=%s to_status=%s attempt_id=%s",
            IngestionAttemptStatus.IDLE,
            IngestionAttemptStatus.RUNNING,
            "attempt-1",
        )

    def test_start_from_complete_creates_new_attempt_id(self) -> None:
        registry = IngestionAttemptStateRegistry()

        with patch(
            "app.ingestion.attempt_state.uuid4",
            side_effect=("attempt-1", "attempt-2"),
        ):
            first_state = registry.start_attempt()
            first_workspace = registry.get_attempt_workspace(first_state.attempt_id)
            registry.complete_attempt(first_state.attempt_id)
            second_state = registry.start_attempt()
            second_workspace = registry.get_attempt_workspace(second_state.attempt_id)

        self.assertEqual(second_state.status, IngestionAttemptStatus.RUNNING)
        self.assertEqual(second_state.attempt_id, "attempt-2")
        self.assertNotEqual(first_state.attempt_id, second_state.attempt_id)
        self.assertIsNotNone(first_workspace)
        self.assertIsNotNone(second_workspace)
        self.assertNotEqual(
            first_workspace.workspace_path,
            second_workspace.workspace_path,
        )
        self.assertFalse(first_workspace.workspace_path.exists())
        self.assertIsNone(registry.get_attempt_workspace(first_state.attempt_id))
        self.assertTrue(second_workspace.workspace_path.exists())

    def test_attempt_workspace_is_outside_committed_world_source_storage(self) -> None:
        registry = IngestionAttemptStateRegistry()
        running_state = registry.start_attempt()

        workspace = registry.get_attempt_workspace(running_state.attempt_id)

        self.assertIsNotNone(workspace)
        self.assertFalse(
            workspace.workspace_path.resolve().is_relative_to(
                get_worlds_directory().resolve()
            )
        )

    def test_request_stop_moves_running_attempt_to_stopping(self) -> None:
        registry = IngestionAttemptStateRegistry()
        running_state = registry.start_attempt()

        state = registry.request_stop()

        self.assertEqual(
            state,
            IngestionAttemptState(
                status=IngestionAttemptStatus.STOPPING,
                attempt_id=running_state.attempt_id,
                staged_work_remaining=True,
            ),
        )
        self.assertTrue(registry.is_cancellation_requested(running_state.attempt_id))

    def test_repeated_request_stop_while_stopping_returns_current_state(self) -> None:
        registry = IngestionAttemptStateRegistry()
        registry.start_attempt()
        stopping_state = registry.request_stop()

        with patch("app.ingestion.attempt_state.logger") as logger:
            state = registry.request_stop()

        self.assertEqual(state, stopping_state)
        self.assertEqual(registry.get_state(), stopping_state)
        logger.warning.assert_called_once_with(
            "Ignored repeated ingestion pause request: attempt_id=%s",
            stopping_state.attempt_id,
        )
        logger.info.assert_not_called()
        logger.error.assert_not_called()

    def test_request_stop_failure_leaves_running_state_unchanged(self) -> None:
        registry = IngestionAttemptStateRegistry(
            cancellation_registry=FailingCancellationRegistry(),
        )
        running_state = registry.start_attempt()

        with patch("app.ingestion.attempt_state.logger") as logger:
            with self.assertRaises(IngestionAttemptCancellationError):
                registry.request_stop()

        self.assertEqual(registry.get_state(), running_state)
        logger.error.assert_called_once_with(
            "Failed to set ingestion attempt cancellation flag: "
            "attempt_id=%s error_type=%s",
            running_state.attempt_id,
            "RuntimeError",
            exc_info=True,
        )
        logger.warning.assert_not_called()

    def test_finish_cancellation_with_remaining_work_moves_to_paused(self) -> None:
        registry = IngestionAttemptStateRegistry()
        running_state = registry.start_attempt()
        workspace = registry.get_attempt_workspace(running_state.attempt_id)
        registry.request_stop()

        state = registry.finish_cancellation(
            running_state.attempt_id,
            staged_work_remaining=True,
        )
        paused_workspace = registry.get_attempt_workspace(running_state.attempt_id)

        self.assertEqual(
            state,
            IngestionAttemptState(
                status=IngestionAttemptStatus.PAUSED,
                attempt_id=running_state.attempt_id,
                staged_work_remaining=True,
            ),
        )
        self.assertEqual(paused_workspace, workspace)
        self.assertTrue(registry.is_cancellation_requested(running_state.attempt_id))

    def test_finish_cancellation_without_remaining_work_moves_to_idle(self) -> None:
        registry = IngestionAttemptStateRegistry()
        running_state = registry.start_attempt()
        workspace = registry.get_attempt_workspace(running_state.attempt_id)
        registry.request_stop()

        state = registry.finish_cancellation(
            running_state.attempt_id,
            staged_work_remaining=False,
        )

        self.assertEqual(
            state,
            IngestionAttemptState(
                status=IngestionAttemptStatus.IDLE,
                attempt_id=None,
                staged_work_remaining=False,
            ),
        )
        self.assertIsNotNone(workspace)
        self.assertFalse(workspace.workspace_path.exists())
        self.assertIsNone(registry.get_attempt_workspace(running_state.attempt_id))
        self.assertFalse(registry.is_cancellation_requested(running_state.attempt_id))

    def test_resume_paused_attempt_returns_to_running_with_same_attempt_id(self) -> None:
        registry = IngestionAttemptStateRegistry()
        running_state = registry.start_attempt()
        paused_workspace = registry.get_attempt_workspace(running_state.attempt_id)
        registry.request_stop()
        registry.finish_cancellation(
            running_state.attempt_id,
            staged_work_remaining=True,
        )

        state = registry.resume_attempt()
        resumed_workspace = registry.get_attempt_workspace(running_state.attempt_id)

        self.assertEqual(
            state,
            IngestionAttemptState(
                status=IngestionAttemptStatus.RUNNING,
                attempt_id=running_state.attempt_id,
                staged_work_remaining=True,
            ),
        )
        self.assertEqual(resumed_workspace, paused_workspace)
        self.assertFalse(registry.is_cancellation_requested(running_state.attempt_id))

    def test_complete_running_attempt_moves_to_complete(self) -> None:
        registry = IngestionAttemptStateRegistry()
        running_state = registry.start_attempt()
        workspace = registry.get_attempt_workspace(running_state.attempt_id)

        state = registry.complete_attempt(running_state.attempt_id)

        self.assertEqual(
            state,
            IngestionAttemptState(
                status=IngestionAttemptStatus.COMPLETE,
                attempt_id=running_state.attempt_id,
                staged_work_remaining=False,
            ),
        )
        self.assertIsNotNone(workspace)
        self.assertFalse(workspace.workspace_path.exists())
        self.assertIsNone(registry.get_attempt_workspace(running_state.attempt_id))
        self.assertFalse(registry.is_cancellation_requested(running_state.attempt_id))

    def test_stale_attempt_id_cannot_complete_newer_attempt(self) -> None:
        registry = IngestionAttemptStateRegistry()

        with patch(
            "app.ingestion.attempt_state.uuid4",
            side_effect=("attempt-1", "attempt-2"),
        ):
            stale_state = registry.start_attempt()
            registry.complete_attempt(stale_state.attempt_id)
            current_state = registry.start_attempt()
            current_workspace = registry.get_attempt_workspace(current_state.attempt_id)

        with patch("app.ingestion.attempt_state.logger") as logger:
            with self.assertRaises(StaleIngestionAttemptResultError):
                registry.complete_attempt(stale_state.attempt_id)

        self.assertEqual(registry.get_state(), current_state)
        self.assertIsNone(registry.get_attempt_workspace(stale_state.attempt_id))
        self.assertEqual(
            registry.get_attempt_workspace(current_state.attempt_id),
            current_workspace,
        )
        logger.warning.assert_called_once_with("Rejected stale ingestion attempt result.")
        logger.error.assert_not_called()

    def test_stale_attempt_id_cannot_cancel_newer_attempt(self) -> None:
        registry = IngestionAttemptStateRegistry()

        with patch(
            "app.ingestion.attempt_state.uuid4",
            side_effect=("attempt-1", "attempt-2"),
        ):
            stale_state = registry.start_attempt()
            registry.request_stop()
            registry.finish_cancellation(
                stale_state.attempt_id,
                staged_work_remaining=False,
            )
            current_state = registry.start_attempt()
            stopping_state = registry.request_stop()

        with patch("app.ingestion.attempt_state.logger") as logger:
            with self.assertRaises(StaleIngestionAttemptResultError):
                registry.finish_cancellation(
                    stale_state.attempt_id,
                    staged_work_remaining=True,
                )

        self.assertEqual(registry.get_state(), stopping_state)
        self.assertEqual(stopping_state.attempt_id, current_state.attempt_id)
        logger.warning.assert_called_once_with("Rejected stale ingestion attempt result.")
        logger.error.assert_not_called()

    def test_invalid_transition_leaves_state_unchanged_and_logs_warning(self) -> None:
        registry = IngestionAttemptStateRegistry()
        original_state = registry.get_state()

        with patch("app.ingestion.attempt_state.logger") as logger:
            with self.assertRaises(InvalidIngestionAttemptTransitionError):
                registry.request_stop()

        self.assertEqual(registry.get_state(), original_state)
        logger.warning.assert_called_once_with(
            "Invalid ingestion attempt state transition: %s",
            "Cannot pause ingestion from current state.",
        )
        logger.info.assert_not_called()
        logger.error.assert_not_called()

    def test_request_stop_from_paused_or_complete_logs_warning(self) -> None:
        registry = IngestionAttemptStateRegistry()
        running_state = registry.start_attempt()
        registry.request_stop()
        paused_state = registry.finish_cancellation(
            running_state.attempt_id,
            staged_work_remaining=True,
        )

        with patch("app.ingestion.attempt_state.logger") as logger:
            with self.assertRaises(InvalidIngestionAttemptTransitionError):
                registry.request_stop()

        self.assertEqual(registry.get_state(), paused_state)
        logger.warning.assert_called_once_with(
            "Invalid ingestion attempt state transition: %s",
            "Cannot pause ingestion from current state.",
        )
        logger.info.assert_not_called()
        logger.error.assert_not_called()

        registry.resume_attempt()
        complete_state = registry.complete_attempt(running_state.attempt_id)

        with patch("app.ingestion.attempt_state.logger") as logger:
            with self.assertRaises(InvalidIngestionAttemptTransitionError):
                registry.request_stop()

        self.assertEqual(registry.get_state(), complete_state)
        logger.warning.assert_called_once_with(
            "Invalid ingestion attempt state transition: %s",
            "Cannot pause ingestion from current state.",
        )
        logger.info.assert_not_called()
        logger.error.assert_not_called()

    def test_unexpected_state_model_failure_logs_error(self) -> None:
        registry = IngestionAttemptStateRegistry()

        with (
            patch("app.ingestion.attempt_state.uuid4", return_value="attempt-1"),
            patch(
                "app.ingestion.attempt_state.validate_attempt_state",
                side_effect=ValueError("state failed"),
            ),
            patch("app.ingestion.attempt_state.logger") as logger,
        ):
            with self.assertRaises(RuntimeError):
                registry.start_attempt()

        logger.error.assert_called_once_with(
            "Unexpected ingestion attempt state failure.",
            exc_info=True,
        )

    def test_workspace_creation_failure_leaves_state_unchanged_and_logs_error(
        self,
    ) -> None:
        registry = IngestionAttemptStateRegistry()
        original_state = registry.get_state()
        private_path = str(Path("private") / "attempt")

        with (
            patch(
                "app.ingestion.attempt_workspace.Path.mkdir",
                side_effect=OSError(private_path),
            ),
            patch("app.ingestion.attempt_workspace.logger") as logger,
        ):
            with self.assertRaises(IngestionAttemptWorkspaceError):
                registry.start_attempt()

        self.assertEqual(registry.get_state(), original_state)
        logger.error.assert_called_once_with(
            "Failed to create temporary ingestion workspace."
        )
        self.assertNotIn(private_path, str(logger.method_calls))

    def test_missing_workspace_cleanup_logs_debug_and_does_not_raise(self) -> None:
        registry = IngestionAttemptWorkspaceRegistry()

        with patch("app.ingestion.attempt_workspace.logger") as logger:
            registry.remove_attempt_workspace("attempt-1")

        logger.debug.assert_called_once_with(
            "Temporary ingestion workspace already cleaned: attempt_id=%s",
            "attempt-1",
        )
        logger.error.assert_not_called()

    def test_workspace_cleanup_failure_logs_error_without_raw_path(self) -> None:
        private_path = str(Path("private") / "workspace")

        with tempfile.TemporaryDirectory() as temp_directory:
            registry = IngestionAttemptWorkspaceRegistry(Path(temp_directory))
            workspace = registry.create_attempt_workspace("attempt-1")

            with (
                patch(
                    "app.ingestion.attempt_workspace.shutil.rmtree",
                    side_effect=OSError(private_path),
                ),
                patch("app.ingestion.attempt_workspace.logger") as logger,
            ):
                registry.remove_attempt_workspace("attempt-1")

            self.assertTrue(workspace.workspace_path.exists())

        logger.error.assert_called_once()
        self.assertNotIn(private_path, str(logger.method_calls))

    def test_startup_cleanup_deletes_only_abandoned_ingestion_workspaces(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            workspace_parent = root / "user" / "data" / "ingestion-workspaces"
            abandoned_workspace = workspace_parent / f"{WORKSPACE_DIRECTORY_PREFIX}old"
            unrelated_directory = workspace_parent / "manual-folder"
            committed_sources = (
                root
                / "user"
                / "worlds"
                / "12345678-1234-5678-1234-567812345678"
                / "sources"
            )
            abandoned_workspace.mkdir(parents=True)
            unrelated_directory.mkdir()
            committed_sources.mkdir(parents=True)
            (committed_sources / "source.txt").write_text("committed", encoding="utf-8")

            cleanup_count = cleanup_abandoned_attempt_workspaces(workspace_parent)

            self.assertEqual(cleanup_count, 1)
            self.assertFalse(abandoned_workspace.exists())
            self.assertTrue(unrelated_directory.exists())
            self.assertTrue(committed_sources.exists())
            self.assertTrue((committed_sources / "source.txt").exists())

    def test_attempt_state_does_not_change_global_or_world_database_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            world_connection = sqlite3.connect(":memory:")
            world_connection.row_factory = sqlite3.Row
            try:
                database_path = Path(temp_directory) / "app.sqlite"
                connection = bootstrap_global_database(database_path)
                apply_world_migrations(world_connection)

                registry = IngestionAttemptStateRegistry()
                running_state = registry.start_attempt()
                registry.request_stop()
                registry.finish_cancellation(
                    running_state.attempt_id,
                    staged_work_remaining=True,
                )
                registry.resume_attempt()
                registry.complete_attempt(running_state.attempt_id)

                self.assertEqual(get_schema_version(connection), 5)
                self.assertEqual(get_world_schema_version(world_connection), 4)
                self.assertIsNone(
                    connection.execute(
                        """
                        SELECT name
                        FROM sqlite_master
                        WHERE type = 'table' AND name LIKE '%attempt%'
                        """
                    ).fetchone()
                )
                self.assertIsNone(
                    world_connection.execute(
                        """
                        SELECT name
                        FROM sqlite_master
                        WHERE type = 'table' AND name LIKE '%attempt%'
                        """
                    ).fetchone()
                )
            finally:
                world_connection.close()
                close_global_connection()


class FailingCancellationRegistry(IngestionAttemptCancellationRegistry):
    def request_cancellation(self, attempt_id: str) -> None:
        raise RuntimeError("flag failed")


if __name__ == "__main__":
    unittest.main()
