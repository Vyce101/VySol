import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.draft_worlds.registry import DraftWorldRegistry
from app.draft_worlds.splitter_settings import SplitterSettings
from app.ingestion.active_staged_batch import (
    ActiveStagedBatchRegistry,
    StagedBatchAttemptKind,
    StagedBatchAttemptTarget,
)
from app.ingestion.app_close_cancellation import AppCloseAttemptCancellationCoordinator
from app.ingestion.attempt_cancellation import clear_attempt_cancellation
from app.ingestion.attempt_start import IngestionAttemptStartRegistry
from app.ingestion.attempt_state import (
    IngestionAttemptCancellationError,
    IngestionAttemptCancellationRegistry,
    IngestionAttemptPhase,
    IngestionAttemptState,
    IngestionAttemptStateRegistry,
    IngestionAttemptStatus,
    IngestionAttemptWorkspaceError,
    InvalidIngestionAttemptTransitionError,
    StaleIngestionAttemptResultError,
    get_ingestion_attempt_cancellation_registry,
)
from app.ingestion.attempt_workspace import (
    AbandonedIngestionWorkspaceCleanupError,
    IngestionAttemptWorkspaceRegistry,
    WORKSPACE_DIRECTORY_PREFIX,
    cleanup_abandoned_attempt_workspaces,
)
from app.ingestion.new_world_commit import (
    NewWorldBatchValidationError,
    commit_new_world_batch,
)
from app.ingestion.staging.source_staging_state import (
    SourceStagingStateRegistry,
    TemporarySourceStagingEntry,
)
from app.storage.database import bootstrap_global_database, close_global_connection
from app.storage.migrations import get_schema_version
from app.storage.paths import get_worlds_directory
from app.storage.world_migrations import apply_world_migrations, get_world_schema_version
from app.storage.worlds import (
    NewCommittedWorld,
    create_committed_world,
    get_committed_world,
)


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
                phase=IngestionAttemptPhase.NOT_STARTED,
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
                phase=IngestionAttemptPhase.PREFLIGHT,
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

    def test_updates_current_running_attempt_phase(self) -> None:
        registry = IngestionAttemptStateRegistry()
        running_state = registry.start_attempt()

        updated_state = registry.update_attempt_phase(
            running_state.attempt_id,
            IngestionAttemptPhase.SPLITTING,
        )

        self.assertEqual(updated_state.phase, IngestionAttemptPhase.SPLITTING)
        self.assertEqual(registry.get_state(), updated_state)

    def test_stale_attempt_id_cannot_update_phase(self) -> None:
        registry = IngestionAttemptStateRegistry()

        with patch(
            "app.ingestion.attempt_state.uuid4",
            side_effect=("attempt-1", "attempt-2"),
        ):
            stale_state = registry.start_attempt()
            registry.complete_attempt(stale_state.attempt_id)
            current_state = registry.start_attempt()

        with patch("app.ingestion.attempt_state.logger") as logger:
            with self.assertRaises(StaleIngestionAttemptResultError):
                registry.update_attempt_phase(
                    stale_state.attempt_id,
                    IngestionAttemptPhase.PARSING,
                )

        self.assertEqual(registry.get_state(), current_state)
        logger.warning.assert_called_once_with("Rejected stale ingestion attempt result.")

    def test_non_running_attempt_cannot_update_phase(self) -> None:
        registry = IngestionAttemptStateRegistry()
        running_state = registry.start_attempt()
        complete_state = registry.complete_attempt(running_state.attempt_id)

        with patch("app.ingestion.attempt_state.logger") as logger:
            with self.assertRaises(InvalidIngestionAttemptTransitionError):
                registry.update_attempt_phase(
                    running_state.attempt_id,
                    IngestionAttemptPhase.PARSING,
                )

        self.assertEqual(registry.get_state(), complete_state)
        logger.warning.assert_called_once_with(
            "Invalid ingestion attempt state transition: %s",
            "Attempt result does not match current state.",
        )

    def test_pause_resume_preserves_attempt_phase(self) -> None:
        registry = IngestionAttemptStateRegistry()
        running_state = registry.start_attempt()
        registry.update_attempt_phase(
            running_state.attempt_id,
            IngestionAttemptPhase.TEXT_COMMITTED,
        )

        stopping_state = registry.request_stop()
        paused_state = registry.finish_cancellation(
            running_state.attempt_id,
            staged_work_remaining=True,
        )
        resumed_state = registry.resume_attempt()

        self.assertEqual(stopping_state.phase, IngestionAttemptPhase.TEXT_COMMITTED)
        self.assertEqual(paused_state.phase, IngestionAttemptPhase.TEXT_COMMITTED)
        self.assertEqual(resumed_state.phase, IngestionAttemptPhase.TEXT_COMMITTED)

    def test_terminal_cancellation_resets_attempt_phase(self) -> None:
        registry = IngestionAttemptStateRegistry()
        running_state = registry.start_attempt()
        registry.update_attempt_phase(
            running_state.attempt_id,
            IngestionAttemptPhase.SPLITTING,
        )
        registry.request_stop()

        idle_state = registry.finish_cancellation(
            running_state.attempt_id,
            staged_work_remaining=False,
        )

        self.assertEqual(idle_state.phase, IngestionAttemptPhase.NOT_STARTED)

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
                phase=IngestionAttemptPhase.PREFLIGHT,
            ),
        )
        self.assertNotEqual(state.status, IngestionAttemptStatus.PAUSED)
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
        self.assertIsNotNone(workspace)
        registry.request_stop()

        with patch("app.ingestion.attempt_state.logger") as logger:
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
                phase=IngestionAttemptPhase.PREFLIGHT,
            ),
        )
        self.assertEqual(paused_workspace, workspace)
        self.assertTrue(workspace.workspace_path.exists())
        self.assertTrue(registry.is_cancellation_requested(running_state.attempt_id))
        logger.info.assert_any_call(
            "Ingestion cancellation completed: "
            "attempt_id=%s staged_work_remaining=%s",
            running_state.attempt_id,
            True,
        )

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
                phase=IngestionAttemptPhase.NOT_STARTED,
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
                phase=IngestionAttemptPhase.PREFLIGHT,
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
                phase=IngestionAttemptPhase.NOT_STARTED,
            ),
        )
        self.assertIsNotNone(workspace)
        self.assertFalse(workspace.workspace_path.exists())
        self.assertIsNone(registry.get_attempt_workspace(running_state.attempt_id))
        self.assertFalse(registry.is_cancellation_requested(running_state.attempt_id))

    def test_late_completion_after_stop_request_is_rejected(self) -> None:
        registry = IngestionAttemptStateRegistry()
        running_state = registry.start_attempt()
        workspace = registry.get_attempt_workspace(running_state.attempt_id)
        self.assertIsNotNone(workspace)
        stopping_state = registry.request_stop()

        with patch("app.ingestion.attempt_state.logger") as logger:
            with self.assertRaises(InvalidIngestionAttemptTransitionError):
                registry.complete_attempt(running_state.attempt_id)

        self.assertEqual(registry.get_state(), stopping_state)
        self.assertEqual(
            registry.get_attempt_workspace(running_state.attempt_id),
            workspace,
        )
        self.assertTrue(workspace.workspace_path.exists())
        self.assertTrue(registry.is_cancellation_requested(running_state.attempt_id))
        logger.warning.assert_called_once_with(
            "Rejected late ingestion attempt result after cancellation: "
            "attempt_id=%s status=%s",
            running_state.attempt_id,
            IngestionAttemptStatus.STOPPING,
        )
        logger.info.assert_not_called()
        logger.error.assert_not_called()

    def test_late_completion_after_pause_is_rejected(self) -> None:
        registry = IngestionAttemptStateRegistry()
        running_state = registry.start_attempt()
        workspace = registry.get_attempt_workspace(running_state.attempt_id)
        self.assertIsNotNone(workspace)
        registry.request_stop()
        paused_state = registry.finish_cancellation(
            running_state.attempt_id,
            staged_work_remaining=True,
        )

        with patch("app.ingestion.attempt_state.logger") as logger:
            with self.assertRaises(InvalidIngestionAttemptTransitionError):
                registry.complete_attempt(running_state.attempt_id)

        self.assertEqual(registry.get_state(), paused_state)
        self.assertEqual(
            registry.get_attempt_workspace(running_state.attempt_id),
            workspace,
        )
        self.assertTrue(workspace.workspace_path.exists())
        self.assertTrue(registry.is_cancellation_requested(running_state.attempt_id))
        logger.warning.assert_called_once_with(
            "Rejected late ingestion attempt result after cancellation: "
            "attempt_id=%s status=%s",
            running_state.attempt_id,
            IngestionAttemptStatus.PAUSED,
        )
        logger.info.assert_not_called()
        logger.error.assert_not_called()

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

            with patch("app.ingestion.attempt_workspace.logger") as logger:
                cleanup_count = cleanup_abandoned_attempt_workspaces(workspace_parent)

            self.assertEqual(cleanup_count, 1)
            self.assertFalse(abandoned_workspace.exists())
            self.assertTrue(unrelated_directory.exists())
            self.assertTrue(committed_sources.exists())
            self.assertTrue((committed_sources / "source.txt").exists())
            logger.info.assert_any_call(
                "Cleaned abandoned temporary ingestion workspaces: count=%s",
                1,
            )

    def test_startup_cleanup_failure_logs_error_and_critical_inconsistency(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            workspace_parent = Path(temp_directory) / "ingestion-workspaces"
            abandoned_workspace = workspace_parent / f"{WORKSPACE_DIRECTORY_PREFIX}old"
            abandoned_workspace.mkdir(parents=True)

            with (
                patch(
                    "app.ingestion.attempt_workspace.shutil.rmtree",
                    side_effect=OSError,
                ),
                patch("app.ingestion.attempt_workspace.logger") as logger,
            ):
                with self.assertRaises(AbandonedIngestionWorkspaceCleanupError):
                    cleanup_abandoned_attempt_workspaces(workspace_parent)

            logger.error.assert_called_once()
            logger.critical.assert_called_once_with(
                "Unrecoverable startup cleanup inconsistency: "
                "remaining_workspace_count=%s",
                1,
            )
            self.assertTrue(abandoned_workspace.exists())

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


class AppCloseAttemptCancellationTests(unittest.TestCase):
    def tearDown(self) -> None:
        close_global_connection()

    def test_app_close_cancels_new_world_attempt_and_discards_draft_state(
        self,
    ) -> None:
        with make_app_close_fixture() as fixture:
            draft_world = fixture.draft_world_registry.create_draft_world()
            fixture.source_staging_registry.replace_staging_state(
                "staging-1",
                [make_staging_entry("entry-1", "one.txt")],
            )
            active_attempt = fixture.start_registry.start_staged_batch_attempt(
                "staging-1",
                StagedBatchAttemptTarget(
                    StagedBatchAttemptKind.NEW_WORLD,
                    draft_world.draft_id,
                ),
            )
            attempt_id = active_attempt.attempt_state.attempt_id
            workspace = fixture.attempt_state_registry.get_attempt_workspace(attempt_id)
            self.assertIsNotNone(workspace)

            with patch("app.ingestion.app_close_cancellation.logger") as logger:
                cancelled_state = fixture.coordinator.cancel_for_app_close()

            self.assertEqual(cancelled_state.status, IngestionAttemptStatus.STOPPING)
            self.assertFalse(cancelled_state.staged_work_remaining)
            self.assertTrue(
                fixture.attempt_state_registry.is_cancellation_requested(attempt_id)
            )
            self.assertIsNone(
                fixture.source_staging_registry.get_staging_state("staging-1")
            )
            self.assertIsNone(
                fixture.draft_world_registry.get_draft_world(draft_world.draft_id)
            )
            self.assertIsNone(
                fixture.active_batch_registry.get_current_staged_batch_attempt()
            )
            self.assertIsNone(
                fixture.attempt_state_registry.get_attempt_workspace(attempt_id)
            )
            self.assertTrue(workspace.workspace_path.exists())
            logger.info.assert_called_once_with(
                "Cancelled ingestion attempt for app close: "
                "attempt_id=%s attempt_kind=%s staging_context_id=%s source_count=%s",
                attempt_id,
                StagedBatchAttemptKind.NEW_WORLD,
                "staging-1",
                1,
            )

            with self.assertRaises(InvalidIngestionAttemptTransitionError):
                fixture.attempt_state_registry.complete_attempt(attempt_id)

            with self.assertRaises(NewWorldBatchValidationError):
                try:
                    commit_new_world_batch(
                        make_new_world_request(),
                        make_splitter_settings(),
                        workspace,
                        (),
                    )
                finally:
                    clear_attempt_cancellation(attempt_id)

    def test_app_close_discards_existing_world_staging_without_changing_world(
        self,
    ) -> None:
        with make_app_close_fixture() as fixture:
            app_connection = bootstrap_global_database(
                fixture.repo_root / "user" / "data" / "app.sqlite",
            )
            committed_world = create_committed_world(
                make_new_world_request("Existing World"),
                app_connection,
            )
            fixture.source_staging_registry.replace_staging_state(
                "existing-staging-1",
                [make_staging_entry("entry-1", "one.txt")],
            )
            active_attempt = fixture.start_registry.start_staged_batch_attempt(
                "existing-staging-1",
                StagedBatchAttemptTarget(
                    StagedBatchAttemptKind.EXISTING_WORLD,
                    committed_world.world_id,
                ),
            )

            fixture.coordinator.cancel_for_app_close()

            self.assertTrue(
                fixture.attempt_state_registry.is_cancellation_requested(
                    active_attempt.attempt_state.attempt_id,
                )
            )
            self.assertIsNone(
                fixture.source_staging_registry.get_staging_state(
                    "existing-staging-1",
                )
            )
            self.assertEqual(
                get_committed_world(committed_world.world_id, app_connection),
                committed_world,
            )

    def test_app_close_discards_stopping_and_paused_attempt_resume_state(self) -> None:
        for pause_before_close in (False, True):
            with self.subTest(pause_before_close=pause_before_close):
                with make_app_close_fixture() as fixture:
                    fixture.source_staging_registry.replace_staging_state(
                        "staging-1",
                        [make_staging_entry("entry-1", "one.txt")],
                    )
                    draft_world = fixture.draft_world_registry.create_draft_world()
                    active_attempt = fixture.start_registry.start_staged_batch_attempt(
                        "staging-1",
                        StagedBatchAttemptTarget(
                            StagedBatchAttemptKind.NEW_WORLD,
                            draft_world.draft_id,
                        ),
                    )
                    attempt_id = active_attempt.attempt_state.attempt_id
                    workspace = fixture.attempt_state_registry.get_attempt_workspace(
                        attempt_id,
                    )
                    fixture.attempt_state_registry.request_stop()
                    if pause_before_close:
                        fixture.attempt_state_registry.finish_cancellation(
                            attempt_id,
                            staged_work_remaining=True,
                        )

                    cancelled_state = fixture.coordinator.cancel_for_app_close()

                    self.assertEqual(
                        cancelled_state.status,
                        IngestionAttemptStatus.STOPPING,
                    )
                    self.assertFalse(cancelled_state.staged_work_remaining)
                    self.assertIsNone(
                        fixture.source_staging_registry.get_staging_state("staging-1")
                    )
                    self.assertIsNone(
                        fixture.draft_world_registry.get_draft_world(
                            draft_world.draft_id,
                        )
                    )
                    self.assertIsNone(
                        fixture.attempt_state_registry.get_attempt_workspace(attempt_id)
                    )
                    self.assertIsNotNone(workspace)
                    self.assertTrue(workspace.workspace_path.exists())
                    with self.assertRaises(InvalidIngestionAttemptTransitionError):
                        fixture.attempt_state_registry.resume_attempt()


class FailingCancellationRegistry(IngestionAttemptCancellationRegistry):
    def request_cancellation(self, attempt_id: str) -> None:
        raise RuntimeError("flag failed")


class AppCloseFixture:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        workspace_registry = IngestionAttemptWorkspaceRegistry(
            repo_root / "user" / "data" / "ingestion-workspaces",
        )
        self.attempt_state_registry = IngestionAttemptStateRegistry(
            workspace_registry,
            get_ingestion_attempt_cancellation_registry(),
        )
        self.active_batch_registry = ActiveStagedBatchRegistry(
            self.attempt_state_registry.get_state,
        )
        self.source_staging_registry = SourceStagingStateRegistry(
            self.active_batch_registry,
        )
        self.draft_world_registry = DraftWorldRegistry()
        self.start_registry = IngestionAttemptStartRegistry(
            self.attempt_state_registry,
            self.source_staging_registry,
            self.active_batch_registry,
        )
        self.coordinator = AppCloseAttemptCancellationCoordinator(
            self.attempt_state_registry,
            self.active_batch_registry,
            self.source_staging_registry,
            self.draft_world_registry,
        )


class AppCloseFixtureContext:
    def __enter__(self) -> AppCloseFixture:
        self._temp_directory = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._temp_directory.name) / "repo"
        self._repo_root_patch = patch("app.storage.paths.REPO_ROOT", self.repo_root)
        self._repo_root_patch.start()
        return AppCloseFixture(self.repo_root)

    def __exit__(self, *args: object) -> None:
        close_global_connection()
        self._repo_root_patch.stop()
        self._temp_directory.cleanup()


def make_app_close_fixture() -> AppCloseFixtureContext:
    return AppCloseFixtureContext()


def make_staging_entry(
    staging_entry_id: str,
    source_file_path: str,
) -> TemporarySourceStagingEntry:
    return TemporarySourceStagingEntry(
        staging_entry_id=staging_entry_id,
        source_file_path=Path(source_file_path),
        source_file_type="txt",
        is_valid=True,
        error_message=None,
    )


def make_new_world_request(display_name: str = "Atomic World") -> NewCommittedWorld:
    return NewCommittedWorld(
        display_name=display_name,
        description="Committed after first batch",
        background_asset_id="builtin-image-main-world",
        font_asset_id="builtin-font-inter",
    )


def make_splitter_settings() -> SplitterSettings:
    return SplitterSettings(
        chunk_size=5,
        max_lookback_size=0,
        overlap_size=2,
        splitter_version="ignored-caller-version",
    )


if __name__ == "__main__":
    unittest.main()
