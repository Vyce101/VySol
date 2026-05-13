import tempfile
import unittest
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException, status

from app.draft_worlds.registry import DraftWorldRegistry
from app.draft_worlds.routes import (
    create_draft_world_detail,
    read_draft_world_detail,
    router,
)
from app.ingestion.staging import SourceStagingStateRegistry
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

    def test_router_exposes_public_draft_world_endpoints(self) -> None:
        routes_by_path_and_method = {
            (route.path, next(iter(route.methods))): route
            for route in router.routes
            if hasattr(route, "methods")
        }
        create_route = routes_by_path_and_method[("/draft-worlds", "POST")]
        read_route = routes_by_path_and_method[("/draft-worlds/{draft_id}", "GET")]

        self.assertEqual(create_route.status_code, status.HTTP_201_CREATED)
        self.assertEqual(read_route.status_code, status.HTTP_200_OK)


class DraftWorldRouteFixture:
    def __init__(self) -> None:
        self.draft_registry = DraftWorldRegistry()
        self.staging_registry = SourceStagingStateRegistry()


def make_route_fixture() -> DraftWorldRouteFixture:
    return DraftWorldRouteFixture()


if __name__ == "__main__":
    unittest.main()
