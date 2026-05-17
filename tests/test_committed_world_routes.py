from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from fastapi import HTTPException
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.committed_worlds.routes import (
    get_committed_world_detail,
    list_committed_world_cards,
    load_committed_world_detail,
    router,
)
from app.draft_worlds.splitter_settings import SplitterSettings
from app.storage.committed_sources import NewCommittedSource, append_committed_source
from app.storage.database import bootstrap_global_database, close_global_connection
from app.storage.world_databases import bootstrap_world_database
from app.storage.world_folders import resolve_world_directory
from app.storage.world_splitter_settings import (
    create_default_world_splitter_settings,
    lock_world_splitter_settings,
    save_world_splitter_settings,
)
from app.storage.worlds import (
    NewCommittedWorld,
    create_committed_world,
    get_committed_world,
    mark_committed_world_used,
)


class CommittedWorldRouteTests(unittest.TestCase):
    def tearDown(self) -> None:
        close_global_connection()

    def test_lists_committed_worlds_as_card_responses(self) -> None:
        with bootstrap_test_database() as connection:
            older_world = create_committed_world(
                NewCommittedWorld(
                    display_name="Zeta",
                    description="Second card",
                    background_asset_id="builtin-image-neon-city",
                    font_asset_id="builtin-font-orbitron-bold",
                ),
                connection,
            )
            newer_world = create_committed_world(
                NewCommittedWorld(
                    display_name="Alpha",
                    description="First card",
                    background_asset_id="builtin-image-main-world",
                    font_asset_id="builtin-font-inter",
                ),
                connection,
            )
            mark_committed_world_used(
                older_world.world_id,
                datetime(2026, 1, 1, 10, 0, 0),
                connection,
            )
            mark_committed_world_used(
                newer_world.world_id,
                datetime(2026, 1, 2, 10, 0, 0),
                connection,
            )

            responses = list_committed_world_cards(connection)

            self.assertEqual(len(responses), 2)
            self.assertEqual(responses[0].world_id, newer_world.world_id)
            self.assertEqual(responses[0].display_name, "Alpha")
            self.assertEqual(responses[0].description, "First card")
            self.assertEqual(responses[0].background_asset_id, "builtin-image-main-world")
            self.assertEqual(
                responses[0].background_image_url,
                "/assets/builtin-image-main-world/file",
            )
            self.assertEqual(responses[0].font_asset_id, "builtin-font-inter")
            self.assertEqual(
                responses[0].font_file_url,
                "/assets/builtin-font-inter/file",
            )
            self.assertEqual(responses[0].last_used_at, "2026-01-02 10:00:00")

    def test_asset_urls_are_quoted(self) -> None:
        with bootstrap_test_database() as connection:
            create_committed_world(
                NewCommittedWorld(
                    display_name="Quoted Assets",
                    background_asset_id="image asset/one",
                    font_asset_id="font asset/two",
                ),
                connection,
            )

            response = list_committed_world_cards(connection)[0]

            self.assertEqual(
                response.background_image_url,
                "/assets/image%20asset%2Fone/file",
            )
            self.assertEqual(
                response.font_file_url,
                "/assets/font%20asset%2Ftwo/file",
            )

    def test_empty_committed_world_list_returns_empty_response(self) -> None:
        with bootstrap_test_database() as connection:
            responses = list_committed_world_cards(connection)

            self.assertEqual(responses, [])

    def test_loads_committed_world_detail_without_refreshing_last_used_at(self) -> None:
        with bootstrap_test_environment() as environment:
            world = environment.create_world()
            environment.create_world_database(world.world_id)

            response = load_committed_world_detail(world.world_id, environment.connection)

            self.assertEqual(response.world_id, world.world_id)
            self.assertEqual(response.display_name, "Detail World")
            self.assertEqual(response.description, "Committed detail")
            self.assertEqual(response.background_asset_id, "builtin-image-main-world")
            self.assertEqual(
                response.background_image_url,
                "/assets/builtin-image-main-world/file",
            )
            self.assertEqual(response.font_asset_id, "builtin-font-inter")
            self.assertEqual(response.font_file_url, "/assets/builtin-font-inter/file")
            self.assertEqual(response.last_used_at, world.last_used_at)
            self.assertEqual(
                get_committed_world(world.world_id, environment.connection).last_used_at,
                world.last_used_at,
            )
            self.assertEqual(response.splitter_settings.chunk_size, 12)
            self.assertEqual(response.splitter_settings.max_lookback_size, 3)
            self.assertEqual(response.splitter_settings.overlap_size, 2)
            self.assertTrue(response.splitter_settings.is_locked)
            self.assertEqual(
                [source.source_id for source in response.committed_sources],
                ["source-a", "source-b"],
            )
            self.assertEqual(
                [source.original_filename for source in response.committed_sources],
                ["volume-one.txt", "volume-two.pdf"],
            )
            self.assertEqual(
                [source.source_file_type for source in response.committed_sources],
                ["txt", "pdf"],
            )
            self.assertEqual(
                [source.book_number for source in response.committed_sources],
                [1, 2],
            )

    def test_missing_committed_world_detail_returns_404_without_creating_storage(
        self,
    ) -> None:
        with bootstrap_test_environment() as environment:
            missing_world_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

            with self.assertRaises(HTTPException) as error:
                get_committed_world_detail(missing_world_id, environment.connection)

            self.assertEqual(error.exception.status_code, 404)
            self.assertFalse(resolve_world_directory(missing_world_id).exists())

    def test_missing_world_database_detail_load_does_not_create_replacement(self) -> None:
        with bootstrap_test_environment() as environment:
            world = environment.create_world()

            with self.assertRaises(HTTPException) as error:
                get_committed_world_detail(world.world_id, environment.connection)

            self.assertEqual(error.exception.status_code, 500)
            self.assertFalse(resolve_world_directory(world.world_id).exists())

    def test_missing_splitter_settings_detail_load_fails(self) -> None:
        with bootstrap_test_environment() as environment:
            world = environment.create_world()
            with close_after_test(bootstrap_world_database(world.world_id)) as connection:
                append_committed_source(connection, make_source())

            with self.assertRaises(HTTPException) as error:
                get_committed_world_detail(world.world_id, environment.connection)

            self.assertEqual(error.exception.status_code, 409)

    def test_unlocked_splitter_settings_detail_load_logs_error_and_fails(self) -> None:
        with bootstrap_test_environment() as environment:
            world = environment.create_world()
            with close_after_test(bootstrap_world_database(world.world_id)) as connection:
                create_default_world_splitter_settings(connection)
                append_committed_source(connection, make_source())

            with patch("app.committed_worlds.routes.logger") as logger:
                with self.assertRaises(HTTPException) as error:
                    get_committed_world_detail(world.world_id, environment.connection)

            self.assertEqual(error.exception.status_code, 409)
            logger.error.assert_called_with(
                "Committed world detail load found unlocked splitter settings."
            )

    def test_committed_source_read_failure_logs_error_and_fails(self) -> None:
        with bootstrap_test_environment() as environment:
            world = environment.create_world()
            environment.create_world_database(world.world_id)

            with (
                patch(
                    "app.committed_worlds.routes.list_committed_sources",
                    side_effect=sqlite3.Error("source read failed"),
                ),
                patch("app.committed_worlds.routes.logger") as logger,
            ):
                with self.assertRaises(HTTPException) as error:
                    get_committed_world_detail(world.world_id, environment.connection)

            self.assertEqual(error.exception.status_code, 500)
            logger.error.assert_called_once_with(
                "Failed to load committed world detail: error_type=%s",
                "Error",
            )

    def test_router_exposes_public_committed_world_card_endpoint(self) -> None:
        routes_by_path_and_method = {
            (route.path, next(iter(route.methods))): route
            for route in router.routes
            if hasattr(route, "methods")
        }
        worlds_route = routes_by_path_and_method[("/worlds", "GET")]

        self.assertEqual(worlds_route.status_code, 200)

    def test_router_exposes_committed_world_detail_endpoint(self) -> None:
        routes_by_path_and_method = {
            (route.path, next(iter(route.methods))): route
            for route in router.routes
            if hasattr(route, "methods")
        }
        detail_route = routes_by_path_and_method[("/worlds/{world_id}/detail", "GET")]

        self.assertEqual(detail_route.status_code, 200)


@contextmanager
def bootstrap_test_database() -> Iterator[sqlite3.Connection]:
    with tempfile.TemporaryDirectory() as temp_directory:
        database_path = Path(temp_directory) / "app.sqlite"
        try:
            yield bootstrap_global_database(database_path)
        finally:
            close_global_connection()


@contextmanager
def bootstrap_test_environment() -> Iterator["CommittedWorldRouteEnvironment"]:
    with tempfile.TemporaryDirectory() as temp_directory:
        repo_root = Path(temp_directory) / "repo"
        database_path = repo_root / "user" / "data" / "app.sqlite"

        with patch("app.storage.paths.REPO_ROOT", repo_root):
            try:
                connection = bootstrap_global_database(database_path)
                yield CommittedWorldRouteEnvironment(connection)
            finally:
                close_global_connection()


class CommittedWorldRouteEnvironment:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create_world(self):
        return create_committed_world(
            NewCommittedWorld(
                display_name="Detail World",
                description="Committed detail",
                background_asset_id="builtin-image-main-world",
                font_asset_id="builtin-font-inter",
            ),
            self.connection,
        )

    def create_world_database(self, world_id: str) -> None:
        with close_after_test(bootstrap_world_database(world_id)) as connection:
            save_world_splitter_settings(
                connection,
                SplitterSettings(
                    chunk_size=12,
                    max_lookback_size=3,
                    overlap_size=2,
                    splitter_version="ignored-caller-version",
                ),
            )
            lock_world_splitter_settings(connection)
            append_committed_source(connection, make_source())
            append_committed_source(
                connection,
                make_source(
                    source_id="source-b",
                    original_filename="volume-two.pdf",
                    stored_path="sources/source-b.pdf",
                    source_file_type="pdf",
                    source_hash="sha256:b",
                    book_number=2,
                ),
            )


@contextmanager
def close_after_test(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield connection
    finally:
        connection.close()


def make_source(**overrides):
    values = {
        "source_id": "source-a",
        "original_filename": "volume-one.txt",
        "stored_path": "sources/source-a.txt",
        "source_file_type": "txt",
        "source_hash": "sha256:a",
        "book_number": 1,
        "committed_at": "2026-05-10 18:30:00",
    }
    values.update(overrides)
    return NewCommittedSource(**values)


if __name__ == "__main__":
    unittest.main()
