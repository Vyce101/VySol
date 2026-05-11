from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.storage.asset_deduplication import (
    calculate_asset_file_hash,
    find_duplicate_asset_id_by_file_hash,
)
from app.storage.assets import ASSET_TYPE_IMAGE, NewAssetMetadata, create_asset_metadata
from app.storage.database import bootstrap_global_database, close_global_connection


class AssetDeduplicationTests(unittest.TestCase):
    def tearDown(self) -> None:
        close_global_connection()

    def test_returns_existing_asset_id_for_matching_file_hash(self) -> None:
        with bootstrap_test_database() as connection:
            with tempfile.TemporaryDirectory() as temp_directory:
                asset_file = Path(temp_directory) / "portrait.png"
                asset_file.write_bytes(b"same image bytes")
                existing_asset = create_asset_metadata(
                    NewAssetMetadata(
                        asset_type=ASSET_TYPE_IMAGE,
                        display_name="Original portrait",
                        stored_path="user/assets/original-portrait.png",
                        is_built_in=False,
                        file_hash=expected_sha256_hash(b"same image bytes"),
                    ),
                    connection,
                )

                duplicate_asset_id = find_duplicate_asset_id_by_file_hash(
                    asset_file,
                    connection,
                )

            self.assertEqual(duplicate_asset_id, existing_asset.asset_id)

    def test_returns_none_for_unmatched_file_hash(self) -> None:
        with bootstrap_test_database() as connection:
            with tempfile.TemporaryDirectory() as temp_directory:
                asset_file = Path(temp_directory) / "new-portrait.png"
                asset_file.write_bytes(b"new image bytes")
                create_asset_metadata(
                    NewAssetMetadata(
                        asset_type=ASSET_TYPE_IMAGE,
                        display_name="Existing portrait",
                        stored_path="user/assets/existing-portrait.png",
                        is_built_in=False,
                        file_hash=expected_sha256_hash(b"existing image bytes"),
                    ),
                    connection,
                )

                duplicate_asset_id = find_duplicate_asset_id_by_file_hash(
                    asset_file,
                    connection,
                )

            self.assertIsNone(duplicate_asset_id)

    def test_deduplicates_by_hash_not_display_name(self) -> None:
        with bootstrap_test_database() as connection:
            with tempfile.TemporaryDirectory() as temp_directory:
                asset_file = Path(temp_directory) / "different-name.png"
                asset_file.write_bytes(b"matching image bytes")
                existing_asset = create_asset_metadata(
                    NewAssetMetadata(
                        asset_type=ASSET_TYPE_IMAGE,
                        display_name="Original Display Name",
                        stored_path="user/assets/original-display-name.png",
                        is_built_in=False,
                        file_hash=expected_sha256_hash(b"matching image bytes"),
                    ),
                    connection,
                )

                duplicate_asset_id = find_duplicate_asset_id_by_file_hash(
                    asset_file,
                    connection,
                )

            self.assertEqual(duplicate_asset_id, existing_asset.asset_id)

    def test_lookup_does_not_require_world_context(self) -> None:
        with bootstrap_test_database() as connection:
            with tempfile.TemporaryDirectory() as temp_directory:
                asset_file = Path(temp_directory) / "global-asset.png"
                asset_file.write_bytes(b"global image bytes")
                existing_asset = create_asset_metadata(
                    NewAssetMetadata(
                        asset_type=ASSET_TYPE_IMAGE,
                        display_name="Global asset",
                        stored_path="user/assets/global-asset.png",
                        is_built_in=False,
                        file_hash=expected_sha256_hash(b"global image bytes"),
                    ),
                    connection,
                )

                duplicate_asset_id = find_duplicate_asset_id_by_file_hash(
                    asset_file,
                    connection,
                )

            self.assertEqual(duplicate_asset_id, existing_asset.asset_id)

    def test_logs_deduplication_hit_without_file_contents(self) -> None:
        file_contents = b"sensitive asset bytes"

        with bootstrap_test_database() as connection:
            with tempfile.TemporaryDirectory() as temp_directory:
                asset_file = Path(temp_directory) / "logged-hit.png"
                asset_file.write_bytes(file_contents)
                create_asset_metadata(
                    NewAssetMetadata(
                        asset_type=ASSET_TYPE_IMAGE,
                        display_name="Logged hit",
                        stored_path="user/assets/logged-hit.png",
                        is_built_in=False,
                        file_hash=expected_sha256_hash(file_contents),
                    ),
                    connection,
                )

                with patch("app.storage.asset_deduplication.logger") as logger:
                    find_duplicate_asset_id_by_file_hash(asset_file, connection)

            logger.info.assert_called_once()
            logged_text = " ".join(
                str(value)
                for call in logger.method_calls
                for value in call.args
            )
            self.assertNotIn(file_contents.decode("utf-8"), logged_text)

    def test_logs_and_reraises_file_read_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            missing_asset_file = Path(temp_directory) / "missing-uploaded-asset.png"

            with patch("app.storage.asset_deduplication.logger") as logger:
                with self.assertRaises(OSError):
                    calculate_asset_file_hash(missing_asset_file)

        logger.error.assert_called_once()

    def test_logs_and_reraises_database_failure(self) -> None:
        connection = sqlite3.connect(":memory:")

        with tempfile.TemporaryDirectory() as temp_directory:
            asset_file = Path(temp_directory) / "database-failure.png"
            asset_file.write_bytes(b"database failure bytes")

            try:
                with patch("app.storage.asset_deduplication.logger") as logger:
                    with self.assertRaises(sqlite3.Error):
                        find_duplicate_asset_id_by_file_hash(asset_file, connection)
            finally:
                connection.close()

        logger.error.assert_called_once()


def expected_sha256_hash(file_contents: bytes) -> str:
    return f"sha256:{hashlib.sha256(file_contents).hexdigest()}"


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
