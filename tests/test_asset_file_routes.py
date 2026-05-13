from collections.abc import Iterator
from contextlib import contextmanager
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.asset_files.routes import read_asset_file, router
from app.storage.assets import ASSET_TYPE_IMAGE, NewAssetMetadata, create_asset_metadata
from app.storage.database import bootstrap_global_database, close_global_connection


class AssetFileRouteTests(unittest.TestCase):
    def tearDown(self) -> None:
        close_global_connection()

    def test_serves_safe_asset_file_by_asset_id(self) -> None:
        with route_environment() as environment:
            asset_file = environment.repo_root / "app" / "assets" / "images" / "card.png"
            asset_file.parent.mkdir(parents=True)
            asset_file.write_bytes(b"image bytes")
            create_asset_metadata(
                NewAssetMetadata(
                    asset_id="asset-card-image",
                    asset_type=ASSET_TYPE_IMAGE,
                    display_name="Card Image",
                    stored_path="app/assets/images/card.png",
                    is_built_in=True,
                ),
                environment.connection,
            )

            response = read_asset_file("asset-card-image")

            self.assertEqual(Path(response.path), asset_file)

    def test_missing_asset_returns_not_found(self) -> None:
        with route_environment():
            with self.assertRaises(HTTPException) as error:
                read_asset_file("missing-asset")

            self.assertEqual(error.exception.status_code, 404)
            self.assertEqual(error.exception.detail, "Asset file was not found.")

    def test_unsafe_asset_path_returns_not_found(self) -> None:
        with route_environment() as environment:
            create_asset_metadata(
                NewAssetMetadata(
                    asset_id="unsafe-card-image",
                    asset_type=ASSET_TYPE_IMAGE,
                    display_name="Unsafe Card Image",
                    stored_path="../secret.png",
                    is_built_in=True,
                ),
                environment.connection,
            )

            with self.assertRaises(HTTPException) as error:
                read_asset_file("unsafe-card-image")

            self.assertEqual(error.exception.status_code, 404)

    def test_router_exposes_public_asset_file_endpoint(self) -> None:
        routes_by_path_and_method = {
            (route.path, next(iter(route.methods))): route
            for route in router.routes
            if hasattr(route, "methods")
        }
        asset_file_route = routes_by_path_and_method[("/assets/{asset_id}/file", "GET")]

        self.assertEqual(asset_file_route.status_code, 200)


@contextmanager
def route_environment() -> Iterator["AssetFileRouteEnvironment"]:
    with tempfile.TemporaryDirectory() as temp_directory:
        repo_root = Path(temp_directory) / "repo"
        database_path = repo_root / "user" / "data" / "app.sqlite"

        with patch("app.storage.asset_files.REPO_ROOT", repo_root):
            connection = bootstrap_global_database(database_path)
            try:
                yield AssetFileRouteEnvironment(repo_root, connection)
            finally:
                close_global_connection()


class AssetFileRouteEnvironment:
    def __init__(self, repo_root: Path, connection) -> None:
        self.repo_root = repo_root
        self.connection = connection


if __name__ == "__main__":
    unittest.main()
