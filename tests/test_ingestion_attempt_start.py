import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ingestion.active_staged_batch import (
    ActiveStagedBatchAttemptError,
    ActiveStagedBatchRegistry,
    RunningStagedBatchSourceAddError,
    StagedBatchAttemptKind,
    StagedBatchAttemptTarget,
)
from app.ingestion.attempt_start import (
    DuplicateIngestionAttemptStartError,
    IngestionAttemptStartOrchestrationError,
    IngestionAttemptStartRegistry,
    InvalidStagedSourceSummary,
    StagedBatchStartValidationError,
)
from app.ingestion.attempt_state import (
    IngestionAttemptStateRegistry,
    IngestionAttemptStatus,
)
from app.ingestion.attempt_workspace import IngestionAttemptWorkspaceRegistry
from app.ingestion.staging.source_staging_state import (
    SourceStagingStateRegistry,
    TemporarySourceStagingEntry,
)


class IngestionAttemptStartTests(unittest.TestCase):
    def test_valid_staged_batch_starts_running_attempt_and_links_batch(self) -> None:
        with make_start_registry() as registries:
            registries.source_staging_registry.replace_staging_state(
                "draft-1",
                [
                    make_entry("entry-1", "private-source-one.txt"),
                    make_entry("entry-2", "private-source-two.pdf"),
                ],
            )

            with (
                patch("app.ingestion.attempt_state.uuid4", return_value="attempt-1"),
                patch("app.ingestion.attempt_start.logger") as logger,
            ):
                active_attempt = registries.start_registry.start_staged_batch_attempt(
                    "draft-1",
                    make_new_world_target("draft-world-1"),
                )

            self.assertEqual(
                active_attempt.attempt_state.status,
                IngestionAttemptStatus.RUNNING,
            )
            self.assertEqual(active_attempt.attempt_state.attempt_id, "attempt-1")
            self.assertEqual(active_attempt.staging_context_id, "draft-1")
            self.assertEqual(
                active_attempt.attempt_kind,
                StagedBatchAttemptKind.NEW_WORLD,
            )
            self.assertEqual(active_attempt.target_id, "draft-world-1")
            self.assertEqual(active_attempt.staging_entry_ids, ("entry-1", "entry-2"))
            self.assertEqual(
                registries.active_batch_registry.get_active_staged_batch_attempt(),
                active_attempt,
            )

            workspace = registries.attempt_state_registry.get_attempt_workspace(
                "attempt-1",
            )

            self.assertIsNotNone(workspace)
            self.assertTrue(workspace.workspace_path.exists())
            logger.info.assert_called_once_with(
                "Started staged batch ingestion attempt: "
                "attempt_id=%s staging_context_id=%s source_count=%s",
                "attempt-1",
                "draft-1",
                2,
            )
            self.assertNotIn("private-source", repr(logger.method_calls))

    def test_invalid_staged_source_blocks_before_attempt_is_created(self) -> None:
        private_path = str(Path("private") / "outline.docx")

        with make_start_registry() as registries:
            registries.source_staging_registry.replace_staging_state(
                "draft-1",
                [
                    make_entry("entry-1", "notes.txt"),
                    make_entry(
                        "entry-2",
                        private_path,
                        source_file_type="docx",
                        is_valid=False,
                        error_message="Unsupported source type.",
                    ),
                ],
            )

            with patch("app.ingestion.attempt_start.logger") as logger:
                with self.assertRaises(StagedBatchStartValidationError) as raised:
                    registries.start_registry.start_staged_batch_attempt(
                        "draft-1",
                        make_new_world_target("draft-world-1"),
                    )

            self.assertEqual(
                raised.exception.invalid_staged_sources,
                (
                    InvalidStagedSourceSummary(
                        staging_entry_id="entry-2",
                        source_file_type="docx",
                        error_message="Unsupported source type.",
                    ),
                ),
            )
            self.assertEqual(
                registries.attempt_state_registry.get_state().status,
                IngestionAttemptStatus.IDLE,
            )
            self.assertIsNone(
                registries.active_batch_registry.get_active_staged_batch_attempt()
            )
            logger.warning.assert_called_once()
            logger.info.assert_not_called()
            logger.error.assert_not_called()
            self.assertNotIn(private_path, repr(logger.method_calls))

    def test_empty_staged_batch_blocks_before_attempt_is_created(self) -> None:
        with make_start_registry() as registries:
            registries.source_staging_registry.create_staging_context("draft-1")

            with patch("app.ingestion.attempt_start.logger") as logger:
                with self.assertRaises(StagedBatchStartValidationError):
                    registries.start_registry.start_staged_batch_attempt(
                        "draft-1",
                        make_new_world_target("draft-world-1"),
                    )

            self.assertEqual(
                registries.attempt_state_registry.get_state().status,
                IngestionAttemptStatus.IDLE,
            )
            logger.warning.assert_called_once_with(
                "Rejected staged batch start: staging_context_id=%s reason=%s",
                "draft-1",
                "empty_staging_list",
            )
            logger.info.assert_not_called()
            logger.error.assert_not_called()

    def test_duplicate_start_while_running_is_blocked_without_new_workspace(self) -> None:
        with make_start_registry() as registries:
            registries.source_staging_registry.replace_staging_state(
                "draft-1",
                [make_entry("entry-1", "one.txt")],
            )

            with patch("app.ingestion.attempt_state.uuid4", return_value="attempt-1"):
                first_attempt = registries.start_registry.start_staged_batch_attempt(
                    "draft-1",
                    make_new_world_target("draft-world-1"),
                )

            first_workspace = registries.attempt_state_registry.get_attempt_workspace(
                "attempt-1",
            )

            with patch("app.ingestion.attempt_start.logger") as logger:
                with self.assertRaises(DuplicateIngestionAttemptStartError):
                    registries.start_registry.start_staged_batch_attempt(
                        "draft-1",
                        make_new_world_target("draft-world-1"),
                    )

            self.assertEqual(
                registries.active_batch_registry.get_active_staged_batch_attempt(),
                first_attempt,
            )
            self.assertEqual(
                registries.attempt_state_registry.get_attempt_workspace("attempt-1"),
                first_workspace,
            )
            logger.warning.assert_called_once_with(
                "Rejected duplicate staged batch start while attempt is running: "
                "attempt_id=%s staging_context_id=%s",
                "attempt-1",
                "draft-1",
            )
            logger.info.assert_not_called()
            logger.error.assert_not_called()

    def test_adding_sources_to_running_staged_batch_is_blocked(self) -> None:
        private_path = str(Path("private") / "two.txt")

        with make_start_registry() as registries:
            original_state = registries.source_staging_registry.replace_staging_state(
                "draft-1",
                [make_entry("entry-1", "one.txt")],
            )

            with patch("app.ingestion.attempt_state.uuid4", return_value="attempt-1"):
                registries.start_registry.start_staged_batch_attempt(
                    "draft-1",
                    make_new_world_target("draft-world-1"),
                )

            with patch("app.ingestion.staging.source_staging_state.logger") as logger:
                with self.assertRaises(RunningStagedBatchSourceAddError):
                    registries.source_staging_registry.add_source_file_paths(
                        "draft-1",
                        [Path(private_path)],
                    )

            self.assertEqual(
                registries.source_staging_registry.get_staging_state("draft-1"),
                original_state,
            )
            logger.warning.assert_called_once_with(
                "Rejected temporary source add while staged batch attempt is running: "
                "staging_context_id=%s",
                "draft-1",
            )
            self.assertNotIn(private_path, repr(logger.method_calls))

    def test_adding_sources_after_pause_is_allowed(self) -> None:
        with make_start_registry() as registries:
            registries.source_staging_registry.replace_staging_state(
                "draft-1",
                [make_entry("entry-1", "one.txt")],
            )

            with patch("app.ingestion.attempt_state.uuid4", return_value="attempt-1"):
                active_attempt = registries.start_registry.start_staged_batch_attempt(
                    "draft-1",
                    make_new_world_target("draft-world-1"),
                )

            registries.attempt_state_registry.request_stop()
            registries.attempt_state_registry.finish_cancellation(
                active_attempt.attempt_state.attempt_id,
                staged_work_remaining=True,
            )

            updated_state = registries.source_staging_registry.add_source_file_paths(
                "draft-1",
                [Path("two.txt")],
            )

            self.assertIsNotNone(updated_state)
            self.assertEqual(len(updated_state.entries), 2)
            self.assertIsNone(
                registries.active_batch_registry.get_active_staged_batch_attempt()
            )

    def test_unexpected_start_failure_logs_error_without_raw_path(self) -> None:
        private_path = str(Path("private") / "attempt")

        with make_start_registry() as registries:
            registries.source_staging_registry.replace_staging_state(
                "draft-1",
                [make_entry("entry-1", "one.txt")],
            )

            with (
                patch.object(
                    registries.attempt_state_registry,
                    "start_attempt",
                    side_effect=RuntimeError(private_path),
                ),
                patch("app.ingestion.attempt_start.logger") as logger,
            ):
                with self.assertRaises(IngestionAttemptStartOrchestrationError):
                    registries.start_registry.start_staged_batch_attempt(
                        "draft-1",
                        make_new_world_target("draft-world-1"),
                    )

            logger.error.assert_called_once()
            self.assertNotIn(private_path, repr(logger.method_calls))
            self.assertEqual(
                registries.attempt_state_registry.get_state().status,
                IngestionAttemptStatus.IDLE,
            )

    def test_invalid_attempt_target_blocks_before_attempt_is_created(self) -> None:
        with make_start_registry() as registries:
            registries.source_staging_registry.replace_staging_state(
                "draft-1",
                [make_entry("entry-1", "one.txt")],
            )

            with patch("app.ingestion.active_staged_batch.logger") as logger:
                with self.assertRaises(ActiveStagedBatchAttemptError):
                    registries.start_registry.start_staged_batch_attempt(
                        "draft-1",
                        "draft-world-1",  # type: ignore[arg-type]
                    )

            self.assertEqual(
                registries.attempt_state_registry.get_state().status,
                IngestionAttemptStatus.IDLE,
            )
            logger.warning.assert_called_once_with(
                "Invalid staged batch attempt target: %s",
                "Staged batch attempt target is invalid.",
            )


class StartRegistryFixture:
    def __init__(self, workspace_parent: Path) -> None:
        workspace_registry = IngestionAttemptWorkspaceRegistry(workspace_parent)
        self.attempt_state_registry = IngestionAttemptStateRegistry(workspace_registry)
        self.active_batch_registry = ActiveStagedBatchRegistry(
            self.attempt_state_registry.get_state,
        )
        self.source_staging_registry = SourceStagingStateRegistry(
            self.active_batch_registry,
        )
        self.start_registry = IngestionAttemptStartRegistry(
            self.attempt_state_registry,
            self.source_staging_registry,
            self.active_batch_registry,
        )


class StartRegistryContext:
    def __enter__(self) -> StartRegistryFixture:
        self._temp_directory = tempfile.TemporaryDirectory()
        self.fixture = StartRegistryFixture(Path(self._temp_directory.name))
        return self.fixture

    def __exit__(self, *args: object) -> None:
        self._temp_directory.cleanup()


def make_start_registry() -> StartRegistryContext:
    return StartRegistryContext()


def make_entry(
    staging_entry_id: str,
    source_file_path: str,
    source_file_type: str = "txt",
    is_valid: bool = True,
    error_message: str | None = None,
) -> TemporarySourceStagingEntry:
    return TemporarySourceStagingEntry(
        staging_entry_id=staging_entry_id,
        source_file_path=Path(source_file_path),
        source_file_type=source_file_type,
        is_valid=is_valid,
        error_message=error_message,
    )


def make_new_world_target(target_id: str) -> StagedBatchAttemptTarget:
    return StagedBatchAttemptTarget(StagedBatchAttemptKind.NEW_WORLD, target_id)


if __name__ == "__main__":
    unittest.main()
