from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.storage.asset_deletion import delete_unused_uploaded_asset
from app.storage.assets import (
    ASSET_TYPE_FONT,
    ASSET_TYPE_IMAGE,
    AssetMetadata,
    NewAssetMetadata,
    create_asset_metadata,
    get_asset_metadata,
)
from app.storage.database import bootstrap_global_database, close_global_connection
from app.storage.worlds import NewCommittedWorld, create_committed_world


class AssetDeletionTests(unittest.TestCase):
    def tearDown(self) -> None:
        close_global_connection()

    def test_deletes_unused_uploaded_image_metadata_and_file(self) -> None:
        with patched_repo_root() as repo_root:
            with bootstrap_test_database(repo_root) as connection:
                asset = create_uploaded_asset(
                    connection,
                    repo_root,
                    ASSET_TYPE_IMAGE,
                    "user/assets/images/unused-image.png",
                )
                asset_file = repo_root / asset.stored_path

                deleted = delete_unused_uploaded_asset(asset.asset_id, connection)

                self.assertTrue(deleted)
                self.assertIsNone(get_asset_metadata(asset.asset_id, connection))
                self.assertFalse(asset_file.exists())

    def test_deletes_unused_uploaded_font_metadata_and_file(self) -> None:
        with patched_repo_root() as repo_root:
            with bootstrap_test_database(repo_root) as connection:
                asset = create_uploaded_asset(
                    connection,
                    repo_root,
                    ASSET_TYPE_FONT,
                    "user/assets/fonts/unused-font.ttf",
                )
                asset_file = repo_root / asset.stored_path

                deleted = delete_unused_uploaded_asset(asset.asset_id, connection)

                self.assertTrue(deleted)
                self.assertIsNone(get_asset_metadata(asset.asset_id, connection))
                self.assertFalse(asset_file.exists())

    def test_rejects_builtin_asset_deletion_and_logs_warning(self) -> None:
        with patched_repo_root() as repo_root:
            with bootstrap_test_database(repo_root) as connection:
                asset = create_asset_metadata(
                    NewAssetMetadata(
                        asset_id="builtin-test-asset",
                        asset_type=ASSET_TYPE_IMAGE,
                        display_name="Built-in test asset",
                        stored_path="app/assets/images/builtin-test.png",
                        is_built_in=True,
                    ),
                    connection,
                )

                with patch("app.storage.asset_deletion.logger") as logger:
                    deleted = delete_unused_uploaded_asset(asset.asset_id, connection)

                self.assertFalse(deleted)
                self.assertEqual(get_asset_metadata(asset.asset_id, connection), asset)
                logger.warning.assert_called_once()

    def test_does_not_delete_asset_used_as_world_background(self) -> None:
        with patched_repo_root() as repo_root:
            with bootstrap_test_database(repo_root) as connection:
                asset = create_uploaded_asset(
                    connection,
                    repo_root,
                    ASSET_TYPE_IMAGE,
                    "user/assets/images/used-background.png",
                )
                create_committed_world(
                    NewCommittedWorld(
                        display_name="Background World",
                        background_asset_id=asset.asset_id,
                        font_asset_id="builtin-font-inter",
                    ),
                    connection,
                )

                deleted = delete_unused_uploaded_asset(asset.asset_id, connection)

                self.assertFalse(deleted)
                self.assertEqual(get_asset_metadata(asset.asset_id, connection), asset)
                self.assertTrue((repo_root / asset.stored_path).exists())

    def test_does_not_delete_asset_used_as_world_font(self) -> None:
        with patched_repo_root() as repo_root:
            with bootstrap_test_database(repo_root) as connection:
                asset = create_uploaded_asset(
                    connection,
                    repo_root,
                    ASSET_TYPE_FONT,
                    "user/assets/fonts/used-font.ttf",
                )
                create_committed_world(
                    NewCommittedWorld(
                        display_name="Font World",
                        background_asset_id="builtin-image-main-world",
                        font_asset_id=asset.asset_id,
                    ),
                    connection,
                )

                deleted = delete_unused_uploaded_asset(asset.asset_id, connection)

                self.assertFalse(deleted)
                self.assertEqual(get_asset_metadata(asset.asset_id, connection), asset)
                self.assertTrue((repo_root / asset.stored_path).exists())

    def test_missing_asset_returns_false(self) -> None:
        with patched_repo_root() as repo_root:
            with bootstrap_test_database(repo_root) as connection:
                deleted = delete_unused_uploaded_asset("missing-asset-id", connection)

                self.assertFalse(deleted)

    def test_unsafe_stored_path_does_not_delete_or_log_raw_path(self) -> None:
        with patched_repo_root() as repo_root:
            with bootstrap_test_database(repo_root) as connection:
                asset = create_asset_metadata(
                    NewAssetMetadata(
                        asset_id="unsafe-delete-asset",
                        asset_type=ASSET_TYPE_IMAGE,
                        display_name="Unsafe delete asset",
                        stored_path="../very-secret-user-path.png",
                        is_built_in=False,
                        file_hash="sha256:unsafe-delete",
                    ),
                    connection,
                )

                with patch("app.storage.asset_files.logger") as logger:
                    deleted = delete_unused_uploaded_asset(asset.asset_id, connection)

                self.assertFalse(deleted)
                self.assertEqual(get_asset_metadata(asset.asset_id, connection), asset)
                logged_text = get_logged_text(logger)
                self.assertNotIn("very-secret-user-path", logged_text)

    def test_file_delete_failure_logs_error_and_preserves_metadata(self) -> None:
        with patched_repo_root() as repo_root:
            with bootstrap_test_database(repo_root) as connection:
                asset = create_uploaded_asset(
                    connection,
                    repo_root,
                    ASSET_TYPE_IMAGE,
                    "user/assets/images/file-failure.png",
                )

                with (
                    patch("pathlib.Path.unlink", side_effect=OSError),
                    patch("app.storage.asset_deletion.logger") as logger,
                ):
                    with self.assertRaises(OSError):
                        delete_unused_uploaded_asset(asset.asset_id, connection)

                self.assertEqual(get_asset_metadata(asset.asset_id, connection), asset)
                logger.error.assert_called_once()

    def test_database_delete_failure_logs_error_and_preserves_file(self) -> None:
        with patched_repo_root() as repo_root:
            with bootstrap_test_database(repo_root) as connection:
                asset = create_uploaded_asset(
                    connection,
                    repo_root,
                    ASSET_TYPE_IMAGE,
                    "user/assets/images/database-failure.png",
                )
                asset_file = repo_root / asset.stored_path
                failing_connection = FailingDeleteConnection(connection)

                with patch("app.storage.asset_deletion.logger") as logger:
                    with self.assertRaises(sqlite3.Error):
                        delete_unused_uploaded_asset(
                            asset.asset_id,
                            failing_connection,
                        )

                self.assertTrue(asset_file.exists())
                self.assertEqual(get_asset_metadata(asset.asset_id, connection), asset)
                logger.error.assert_called_once()


def create_uploaded_asset(
    connection: sqlite3.Connection,
    repo_root: Path,
    asset_type: str,
    stored_path: str,
) -> AssetMetadata:
    asset_file = repo_root / stored_path
    asset_file.parent.mkdir(parents=True, exist_ok=True)
    asset_file.write_bytes(b"uploaded asset bytes")
    return create_asset_metadata(
        NewAssetMetadata(
            asset_id=Path(stored_path).stem,
            asset_type=asset_type,
            display_name=Path(stored_path).stem,
            stored_path=stored_path,
            is_built_in=False,
            file_hash=f"sha256:{Path(stored_path).stem}",
        ),
        connection,
    )


def get_logged_text(logger: object) -> str:
    return " ".join(
        str(value)
        for call in logger.method_calls
        for value in call.args
    )


@contextmanager
def patched_repo_root() -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as temp_directory:
        repo_root = Path(temp_directory) / "repo"
        with patch("app.storage.asset_files.REPO_ROOT", repo_root):
            yield repo_root


@contextmanager
def bootstrap_test_database(repo_root: Path) -> Iterator[sqlite3.Connection]:
    database_path = repo_root / "user" / "data" / "app.sqlite"
    try:
        yield bootstrap_global_database(database_path)
    finally:
        close_global_connection()


class FailingDeleteConnection:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def execute(self, statement: str, parameters=()):
        normalized_statement = " ".join(statement.split()).upper()
        if normalized_statement.startswith("DELETE FROM ASSETS"):
            raise sqlite3.Error("delete failed")

        return self.connection.execute(statement, parameters)

    def commit(self) -> None:
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()


if __name__ == "__main__":
    unittest.main()
