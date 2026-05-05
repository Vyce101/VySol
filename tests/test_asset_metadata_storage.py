from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from app.storage.assets import (
    ASSET_TYPE_FONT,
    ASSET_TYPE_IMAGE,
    AssetMetadataValidationError,
    NewAssetMetadata,
    create_asset_metadata,
    get_asset_metadata,
    list_asset_metadata,
)
from app.storage.database import bootstrap_global_database, close_global_connection
from app.storage.migrations import get_schema_version


class AssetMetadataStorageTests(unittest.TestCase):
    def tearDown(self) -> None:
        close_global_connection()

    def test_migration_creates_assets_table(self) -> None:
        connection = sqlite3.connect(":memory:")

        try:
            from app.storage.migrations import apply_migrations

            apply_migrations(connection)
            table = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = 'assets'
                """
            ).fetchone()

            self.assertIsNotNone(table)
            self.assertEqual(get_schema_version(connection), 2)
        finally:
            connection.close()

    def test_creates_and_reads_builtin_asset_without_file_hash(self) -> None:
        with bootstrap_test_database() as connection:
            created_asset = create_asset_metadata(
                NewAssetMetadata(
                    asset_type=ASSET_TYPE_IMAGE,
                    display_name="Default world image",
                    stored_path="assets/default_world_image.png",
                    is_built_in=True,
                ),
                connection,
            )
            read_asset = get_asset_metadata(created_asset.asset_id, connection)

            UUID(created_asset.asset_id)
            self.assertEqual(read_asset, created_asset)
            self.assertIsNone(created_asset.file_hash)

    def test_creates_uploaded_asset_with_file_hash(self) -> None:
        with bootstrap_test_database() as connection:
            created_asset = create_asset_metadata(
                NewAssetMetadata(
                    asset_type=ASSET_TYPE_IMAGE,
                    display_name="Uploaded portrait",
                    stored_path="user/assets/uploaded_portrait.png",
                    is_built_in=False,
                    file_hash="sha256:example-hash",
                ),
                connection,
            )

            self.assertFalse(created_asset.is_built_in)
            self.assertEqual(created_asset.file_hash, "sha256:example-hash")

    def test_stores_full_font_name_when_available(self) -> None:
        with bootstrap_test_database() as connection:
            created_asset = create_asset_metadata(
                NewAssetMetadata(
                    asset_type=ASSET_TYPE_FONT,
                    display_name="Cinzel Bold",
                    stored_path="user/assets/cinzel-bold.ttf",
                    is_built_in=False,
                    file_hash="sha256:font-hash",
                    full_font_name="Cinzel Bold",
                ),
                connection,
            )

            self.assertEqual(created_asset.full_font_name, "Cinzel Bold")

    def test_lists_assets_in_stable_display_order(self) -> None:
        with bootstrap_test_database() as connection:
            second_asset = create_asset_metadata(
                NewAssetMetadata(
                    asset_type=ASSET_TYPE_IMAGE,
                    display_name="Zeta",
                    stored_path="assets/zeta.png",
                    is_built_in=True,
                ),
                connection,
            )
            first_asset = create_asset_metadata(
                NewAssetMetadata(
                    asset_type=ASSET_TYPE_FONT,
                    display_name="Alpha",
                    stored_path="assets/alpha.ttf",
                    is_built_in=True,
                    full_font_name="Alpha Regular",
                ),
                connection,
            )

            assets = list_asset_metadata(connection)

            self.assertEqual(assets, [first_asset, second_asset])

    def test_rejects_uploaded_asset_without_file_hash_and_logs_warning(self) -> None:
        with bootstrap_test_database() as connection:
            with patch("app.storage.assets.logger") as logger:
                with self.assertRaises(AssetMetadataValidationError):
                    create_asset_metadata(
                        NewAssetMetadata(
                            asset_type=ASSET_TYPE_IMAGE,
                            display_name="Uploaded portrait",
                            stored_path="user/assets/uploaded_portrait.png",
                            is_built_in=False,
                        ),
                        connection,
                    )

            logger.warning.assert_called_once()

    def test_logs_database_failure_and_reraises(self) -> None:
        connection = sqlite3.connect(":memory:")

        try:
            with patch("app.storage.assets.logger") as logger:
                with self.assertRaises(sqlite3.Error):
                    create_asset_metadata(
                        NewAssetMetadata(
                            asset_type=ASSET_TYPE_IMAGE,
                            display_name="Missing table",
                            stored_path="assets/missing-table.png",
                            is_built_in=True,
                        ),
                        connection,
                    )

            logger.error.assert_called_once()
        finally:
            connection.close()


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
