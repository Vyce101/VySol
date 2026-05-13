import tempfile
import unittest
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException, status

from app.draft_worlds.routes import DraftWorldUnsavedCustomizationRequest
from app.draft_worlds.registry import DraftWorldRegistry
from app.draft_worlds.routes import (
    confirm_draft_world_leave,
    create_draft_world_detail,
    read_draft_world_detail,
    read_draft_world_leave_state,
    router,
    update_draft_world_unsaved_customization_changes,
)
from app.ingestion.attempt_state import (
    IngestionAttemptPhase,
    IngestionAttemptStateRegistry,
)
from app.ingestion.staging import SourceStagingStateRegistry
from app.ingestion.staging.source_staging_state import TemporarySourceStagingEntry
from app.storage.database import bootstrap_global_database, close_global_connection


class DraftWorldRouteTests(unittest.TestCase):
    def tearDown(self) -> None:
        close_global_connection()

    def test_create_draft_world_returns_defaults_and_empty_staged_sources(self) -> None:
        fixture = make_route_fixture()

        response = create_draft_world_detail(
            fixture.draft_registry,
            fixture.staging_registry,
        )

        UUID(response.draft_id)
        self.assertEqual(
            response.splitter_settings.chunk_size,
            4000,
        )
        self.assertEqual(response.splitter_settings.max_lookback_size, 1000)
        self.assertEqual(response.splitter_settings.overlap_size, 400)
        self.assertEqual(response.splitter_settings.splitter_version, "1")
        self.assertEqual(response.staged_sources, [])
        self.assertFalse(response.has_unsaved_customization_changes)

    def test_create_draft_world_creates_matching_temporary_staging_context(self) -> None:
        fixture = make_route_fixture()

        response = create_draft_world_detail(
            fixture.draft_registry,
            fixture.staging_registry,
        )
        staging_state = fixture.staging_registry.get_staging_state(response.draft_id)

        self.assertIsNotNone(staging_state)
        self.assertEqual(staging_state.staging_context_id, response.draft_id)
        self.assertEqual(staging_state.entries, ())

    def test_create_draft_world_does_not_write_committed_storage(self) -> None:
        fixture = make_route_fixture()

        with tempfile.TemporaryDirectory() as temp_directory:
            try:
                database_path = Path(temp_directory) / "app.sqlite"
                connection = bootstrap_global_database(database_path)

                create_draft_world_detail(
                    fixture.draft_registry,
                    fixture.staging_registry,
                )
                committed_world_count = connection.execute(
                    "SELECT COUNT(*) AS world_count FROM worlds"
                ).fetchone()["world_count"]
            finally:
                close_global_connection()

        self.assertEqual(committed_world_count, 0)

    def test_read_draft_world_returns_existing_backend_state(self) -> None:
        fixture = make_route_fixture()
        created_response = create_draft_world_detail(
            fixture.draft_registry,
            fixture.staging_registry,
        )

        read_response = read_draft_world_detail(
            created_response.draft_id,
            fixture.draft_registry,
            fixture.staging_registry,
        )

        self.assertEqual(read_response, created_response)

    def test_read_missing_draft_world_returns_not_found(self) -> None:
        fixture = make_route_fixture()

        with self.assertRaises(HTTPException) as error:
            read_draft_world_detail(
                "missing-draft-id",
                fixture.draft_registry,
                fixture.staging_registry,
            )

        self.assertEqual(error.exception.status_code, 404)
        self.assertEqual(error.exception.detail, "Draft world was not found.")

    def test_updates_draft_unsaved_customization_changes(self) -> None:
        fixture = make_route_fixture()
        created_response = create_draft_world_detail(
            fixture.draft_registry,
            fixture.staging_registry,
        )

        response = update_draft_world_unsaved_customization_changes(
            created_response.draft_id,
            DraftWorldUnsavedCustomizationRequest(
                has_unsaved_customization_changes=True,
            ),
            fixture.draft_registry,
            fixture.staging_registry,
        )

        draft_world = fixture.draft_registry.get_draft_world(created_response.draft_id)
        self.assertTrue(response.has_unsaved_customization_changes)
        self.assertTrue(draft_world.has_unsaved_customization_changes)

    def test_leave_state_warns_before_text_commit(self) -> None:
        fixture = make_route_fixture()
        created_response = create_draft_world_detail(
            fixture.draft_registry,
            fixture.staging_registry,
        )
        running_state = fixture.attempt_state_registry.start_attempt()

        for phase in (
            IngestionAttemptPhase.PREFLIGHT,
            IngestionAttemptPhase.PARSING,
            IngestionAttemptPhase.SPLITTING,
            IngestionAttemptPhase.ATOMIC_TEXT_COMMIT,
        ):
            with self.subTest(phase=phase):
                fixture.attempt_state_registry.update_attempt_phase(
                    running_state.attempt_id,
                    phase,
                )

                response = read_draft_world_leave_state(
                    created_response.draft_id,
                    fixture.draft_registry,
                    fixture.attempt_state_registry,
                )

                self.assertTrue(response.should_warn_before_leave)
                self.assertTrue(response.should_discard_on_confirmed_leave)
                self.assertFalse(response.is_safe_to_leave)
                self.assertEqual(response.attempt_phase, phase.value)

    def test_leave_state_allows_exit_after_text_commit(self) -> None:
        fixture = make_route_fixture()
        created_response = create_draft_world_detail(
            fixture.draft_registry,
            fixture.staging_registry,
        )
        running_state = fixture.attempt_state_registry.start_attempt()
        fixture.attempt_state_registry.update_attempt_phase(
            running_state.attempt_id,
            IngestionAttemptPhase.TEXT_COMMITTED,
        )

        response = read_draft_world_leave_state(
            created_response.draft_id,
            fixture.draft_registry,
            fixture.attempt_state_registry,
        )

        self.assertFalse(response.should_warn_before_leave)
        self.assertFalse(response.should_discard_on_confirmed_leave)
        self.assertTrue(response.is_safe_to_leave)

    def test_leave_state_warns_after_text_commit_with_unsaved_customization(
        self,
    ) -> None:
        fixture = make_route_fixture()
        created_response = create_draft_world_detail(
            fixture.draft_registry,
            fixture.staging_registry,
        )
        fixture.draft_registry.update_draft_unsaved_customization_changes(
            created_response.draft_id,
            True,
        )
        running_state = fixture.attempt_state_registry.start_attempt()
        fixture.attempt_state_registry.update_attempt_phase(
            running_state.attempt_id,
            IngestionAttemptPhase.TEXT_COMMITTED,
        )

        response = read_draft_world_leave_state(
            created_response.draft_id,
            fixture.draft_registry,
            fixture.attempt_state_registry,
        )

        self.assertTrue(response.has_unsaved_customization_changes)
        self.assertTrue(response.should_warn_before_leave)
        self.assertTrue(response.should_discard_on_confirmed_leave)
        self.assertFalse(response.is_safe_to_leave)

    def test_confirmed_danger_zone_leave_discards_draft_and_staging(self) -> None:
        fixture = make_route_fixture()
        created_response = create_draft_world_detail(
            fixture.draft_registry,
            fixture.staging_registry,
        )
        fixture.staging_registry.replace_staging_state(
            created_response.draft_id,
            [make_staging_entry("entry-1")],
        )

        response = confirm_draft_world_leave(
            created_response.draft_id,
            fixture.draft_registry,
            fixture.staging_registry,
            fixture.attempt_state_registry,
        )

        self.assertTrue(response.was_discarded)
        self.assertIsNone(
            fixture.draft_registry.get_draft_world(created_response.draft_id)
        )
        self.assertIsNone(
            fixture.staging_registry.get_staging_state(created_response.draft_id)
        )

    def test_confirmed_safe_zone_leave_does_not_discard_draft_or_staging(self) -> None:
        fixture = make_route_fixture()
        created_response = create_draft_world_detail(
            fixture.draft_registry,
            fixture.staging_registry,
        )
        staging_state = fixture.staging_registry.replace_staging_state(
            created_response.draft_id,
            [make_staging_entry("entry-1")],
        )
        running_state = fixture.attempt_state_registry.start_attempt()
        fixture.attempt_state_registry.update_attempt_phase(
            running_state.attempt_id,
            IngestionAttemptPhase.TEXT_COMMITTED,
        )

        response = confirm_draft_world_leave(
            created_response.draft_id,
            fixture.draft_registry,
            fixture.staging_registry,
            fixture.attempt_state_registry,
        )

        self.assertFalse(response.was_discarded)
        self.assertIsNotNone(
            fixture.draft_registry.get_draft_world(created_response.draft_id)
        )
        self.assertEqual(
            fixture.staging_registry.get_staging_state(created_response.draft_id),
            staging_state,
        )

    def test_confirmed_leave_does_not_write_worlds_or_delete_assets(self) -> None:
        fixture = make_route_fixture()

        with tempfile.TemporaryDirectory() as temp_directory:
            try:
                database_path = Path(temp_directory) / "app.sqlite"
                connection = bootstrap_global_database(database_path)
                created_response = create_draft_world_detail(
                    fixture.draft_registry,
                    fixture.staging_registry,
                )
                asset_count_before = connection.execute(
                    "SELECT COUNT(*) AS asset_count FROM assets"
                ).fetchone()["asset_count"]

                confirm_draft_world_leave(
                    created_response.draft_id,
                    fixture.draft_registry,
                    fixture.staging_registry,
                    fixture.attempt_state_registry,
                )

                asset_count_after = connection.execute(
                    "SELECT COUNT(*) AS asset_count FROM assets"
                ).fetchone()["asset_count"]
                world_count = connection.execute(
                    "SELECT COUNT(*) AS world_count FROM worlds"
                ).fetchone()["world_count"]
            finally:
                close_global_connection()

        self.assertEqual(asset_count_after, asset_count_before)
        self.assertEqual(world_count, 0)

    def test_router_exposes_public_draft_world_endpoints(self) -> None:
        routes_by_path_and_method = {
            (route.path, next(iter(route.methods))): route
            for route in router.routes
            if hasattr(route, "methods")
        }
        create_route = routes_by_path_and_method[("/draft-worlds", "POST")]
        read_route = routes_by_path_and_method[("/draft-worlds/{draft_id}", "GET")]
        dirty_route = routes_by_path_and_method[
            ("/draft-worlds/{draft_id}/unsaved-customization-changes", "PATCH")
        ]
        leave_state_route = routes_by_path_and_method[
            ("/draft-worlds/{draft_id}/leave-state", "GET")
        ]
        confirmed_leave_route = routes_by_path_and_method[
            ("/draft-worlds/{draft_id}/confirmed-leave", "POST")
        ]

        self.assertEqual(create_route.status_code, status.HTTP_201_CREATED)
        self.assertEqual(read_route.status_code, status.HTTP_200_OK)
        self.assertEqual(dirty_route.status_code, status.HTTP_200_OK)
        self.assertEqual(leave_state_route.status_code, status.HTTP_200_OK)
        self.assertEqual(confirmed_leave_route.status_code, status.HTTP_200_OK)


class DraftWorldRouteFixture:
    def __init__(self) -> None:
        self.draft_registry = DraftWorldRegistry()
        self.staging_registry = SourceStagingStateRegistry()
        self.attempt_state_registry = IngestionAttemptStateRegistry()


def make_route_fixture() -> DraftWorldRouteFixture:
    return DraftWorldRouteFixture()


def make_staging_entry(staging_entry_id: str) -> TemporarySourceStagingEntry:
    return TemporarySourceStagingEntry(
        staging_entry_id=staging_entry_id,
        source_file_path=Path("source.txt"),
        source_file_type="txt",
        is_valid=True,
        error_message=None,
    )


if __name__ == "__main__":
    unittest.main()
