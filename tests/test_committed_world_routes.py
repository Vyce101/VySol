from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.committed_worlds.routes import list_committed_world_cards, router
from app.storage.database import bootstrap_global_database, close_global_connection
from app.storage.worlds import (
    NewCommittedWorld,
    create_committed_world,
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

    def test_router_exposes_public_committed_world_card_endpoint(self) -> None:
        routes_by_path_and_method = {
            (route.path, next(iter(route.methods))): route
            for route in router.routes
            if hasattr(route, "methods")
        }
        worlds_route = routes_by_path_and_method[("/worlds", "GET")]

        self.assertEqual(worlds_route.status_code, 200)


@contextmanager
def bootstrap_test_database() -> Iterator[sqlite3.Connection]:
    with tempfile.TemporaryDirectory() as temp_directory:
        database_path = Path(temp_directory) / "app.sqlite"
        try:
            yield bootstrap_global_database(database_path)
        finally:
            close_global_connection()


if __name__ == "__main__":
    unittest.main()
