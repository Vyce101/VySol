import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ingestion.attempt_state import (
    IngestionAttemptState,
    IngestionAttemptStateRegistry,
    IngestionAttemptStatus,
    InvalidIngestionAttemptTransitionError,
    StaleIngestionAttemptResultError,
)
from app.storage.database import bootstrap_global_database, close_global_connection
from app.storage.migrations import get_schema_version
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
            registry.complete_attempt(first_state.attempt_id)
            second_state = registry.start_attempt()

        self.assertEqual(second_state.status, IngestionAttemptStatus.RUNNING)
        self.assertEqual(second_state.attempt_id, "attempt-2")
        self.assertNotEqual(first_state.attempt_id, second_state.attempt_id)

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

    def test_finish_cancellation_with_remaining_work_moves_to_paused(self) -> None:
        registry = IngestionAttemptStateRegistry()
        running_state = registry.start_attempt()
        registry.request_stop()

        state = registry.finish_cancellation(
            running_state.attempt_id,
            staged_work_remaining=True,
        )

        self.assertEqual(
            state,
            IngestionAttemptState(
                status=IngestionAttemptStatus.PAUSED,
                attempt_id=running_state.attempt_id,
                staged_work_remaining=True,
            ),
        )

    def test_finish_cancellation_without_remaining_work_moves_to_idle(self) -> None:
        registry = IngestionAttemptStateRegistry()
        running_state = registry.start_attempt()
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

    def test_resume_paused_attempt_returns_to_running_with_same_attempt_id(self) -> None:
        registry = IngestionAttemptStateRegistry()
        running_state = registry.start_attempt()
        registry.request_stop()
        registry.finish_cancellation(
            running_state.attempt_id,
            staged_work_remaining=True,
        )

        state = registry.resume_attempt()

        self.assertEqual(
            state,
            IngestionAttemptState(
                status=IngestionAttemptStatus.RUNNING,
                attempt_id=running_state.attempt_id,
                staged_work_remaining=True,
            ),
        )

    def test_complete_running_attempt_moves_to_complete(self) -> None:
        registry = IngestionAttemptStateRegistry()
        running_state = registry.start_attempt()

        state = registry.complete_attempt(running_state.attempt_id)

        self.assertEqual(
            state,
            IngestionAttemptState(
                status=IngestionAttemptStatus.COMPLETE,
                attempt_id=running_state.attempt_id,
                staged_work_remaining=False,
            ),
        )

    def test_stale_attempt_id_cannot_complete_newer_attempt(self) -> None:
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
                registry.complete_attempt(stale_state.attempt_id)

        self.assertEqual(registry.get_state(), current_state)
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
            "Cannot stop ingestion from current state.",
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


if __name__ == "__main__":
    unittest.main()
