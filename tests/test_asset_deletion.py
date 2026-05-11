from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.storage.asset_deletion import (
    delete_unused_uploaded_asset,
    delete_uploaded_asset_with_fallback,
    get_uploaded_asset_deletion_impact,
)
from app.storage.assets import (
    ASSET_TYPE_FONT,
    ASSET_TYPE_IMAGE,
    AssetMetadata,
    NewAssetMetadata,
    create_asset_metadata,
    get_asset_metadata,
)
from app.storage.database import bootstrap_global_database, close_global_connection
from app.storage.default_assets import (
    MAIN_DEFAULT_BACKGROUND_ASSET_ID,
    MAIN_DEFAULT_FONT_ASSET_ID,
)
from app.storage.worlds import (
    NewCommittedWorld,
    create_committed_world,
    get_committed_world,
)


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

    def test_returns_used_uploaded_image_deletion_impact_world_names(self) -> None:
        with patched_repo_root() as repo_root:
            with bootstrap_test_database(repo_root) as connection:
                asset = create_uploaded_asset(
                    connection,
                    repo_root,
                    ASSET_TYPE_IMAGE,
                    "user/assets/images/used-image-impact.png",
                )
                second_world = create_committed_world(
                    NewCommittedWorld(
                        display_name="Zeta World",
                        background_asset_id=asset.asset_id,
                        font_asset_id=MAIN_DEFAULT_FONT_ASSET_ID,
                    ),
                    connection,
                )
                first_world = create_committed_world(
                    NewCommittedWorld(
                        display_name="Alpha World",
                        background_asset_id=asset.asset_id,
                        font_asset_id=MAIN_DEFAULT_FONT_ASSET_ID,
                    ),
                    connection,
                )

                with patch("app.storage.asset_deletion.logger") as logger:
                    impact = get_uploaded_asset_deletion_impact(
                        asset.asset_id,
                        connection,
                    )

                self.assertIsNotNone(impact)
                self.assertEqual(impact.asset_id, asset.asset_id)
                self.assertEqual(impact.asset_type, ASSET_TYPE_IMAGE)
                self.assertEqual(
                    [
                        (world.world_id, world.display_name)
                        for world in impact.affected_worlds
                    ],
                    [
                        (first_world.world_id, "Alpha World"),
                        (second_world.world_id, "Zeta World"),
                    ],
                )
                logger.info.assert_called_once()

    def test_returns_used_uploaded_font_deletion_impact_world_names(self) -> None:
        with patched_repo_root() as repo_root:
            with bootstrap_test_database(repo_root) as connection:
                asset = create_uploaded_asset(
                    connection,
                    repo_root,
                    ASSET_TYPE_FONT,
                    "user/assets/fonts/used-font-impact.ttf",
                )
                world = create_committed_world(
                    NewCommittedWorld(
                        display_name="Font Impact World",
                        background_asset_id=MAIN_DEFAULT_BACKGROUND_ASSET_ID,
                        font_asset_id=asset.asset_id,
                    ),
                    connection,
                )

                impact = get_uploaded_asset_deletion_impact(
                    asset.asset_id,
                    connection,
                )

                self.assertIsNotNone(impact)
                self.assertEqual(impact.asset_type, ASSET_TYPE_FONT)
                self.assertEqual(
                    [
                        (affected_world.world_id, affected_world.display_name)
                        for affected_world in impact.affected_worlds
                    ],
                    [(world.world_id, "Font Impact World")],
                )

    def test_confirmed_image_deletion_falls_back_worlds_and_deletes_asset(
        self,
    ) -> None:
        with patched_repo_root() as repo_root:
            with bootstrap_test_database(repo_root) as connection:
                asset = create_uploaded_asset(
                    connection,
                    repo_root,
                    ASSET_TYPE_IMAGE,
                    "user/assets/images/delete-used-image.png",
                )
                asset_file = repo_root / asset.stored_path
                world = create_committed_world(
                    NewCommittedWorld(
                        display_name="Image Fallback World",
                        background_asset_id=asset.asset_id,
                        font_asset_id=MAIN_DEFAULT_FONT_ASSET_ID,
                    ),
                    connection,
                )

                deleted = delete_uploaded_asset_with_fallback(
                    asset.asset_id,
                    [world.world_id],
                    connection,
                )

                updated_world = get_committed_world(world.world_id, connection)
                self.assertTrue(deleted)
                self.assertIsNone(get_asset_metadata(asset.asset_id, connection))
                self.assertFalse(asset_file.exists())
                self.assertEqual(
                    updated_world.background_asset_id,
                    MAIN_DEFAULT_BACKGROUND_ASSET_ID,
                )
                self.assertEqual(updated_world.font_asset_id, MAIN_DEFAULT_FONT_ASSET_ID)

    def test_confirmed_font_deletion_falls_back_worlds_and_deletes_asset(self) -> None:
        with patched_repo_root() as repo_root:
            with bootstrap_test_database(repo_root) as connection:
                asset = create_uploaded_asset(
                    connection,
                    repo_root,
                    ASSET_TYPE_FONT,
                    "user/assets/fonts/delete-used-font.ttf",
                )
                asset_file = repo_root / asset.stored_path
                world = create_committed_world(
                    NewCommittedWorld(
                        display_name="Font Fallback World",
                        background_asset_id=MAIN_DEFAULT_BACKGROUND_ASSET_ID,
                        font_asset_id=asset.asset_id,
                    ),
                    connection,
                )

                deleted = delete_uploaded_asset_with_fallback(
                    asset.asset_id,
                    [world.world_id],
                    connection,
                )

                updated_world = get_committed_world(world.world_id, connection)
                self.assertTrue(deleted)
                self.assertIsNone(get_asset_metadata(asset.asset_id, connection))
                self.assertFalse(asset_file.exists())
                self.assertEqual(
                    updated_world.background_asset_id,
                    MAIN_DEFAULT_BACKGROUND_ASSET_ID,
                )
                self.assertEqual(updated_world.font_asset_id, MAIN_DEFAULT_FONT_ASSET_ID)

    def test_confirmed_deletion_rejects_stale_world_ids(self) -> None:
        with patched_repo_root() as repo_root:
            with bootstrap_test_database(repo_root) as connection:
                asset = create_uploaded_asset(
                    connection,
                    repo_root,
                    ASSET_TYPE_IMAGE,
                    "user/assets/images/stale-confirmation.png",
                )
                asset_file = repo_root / asset.stored_path
                world = create_committed_world(
                    NewCommittedWorld(
                        display_name="Stale World",
                        background_asset_id=asset.asset_id,
                        font_asset_id=MAIN_DEFAULT_FONT_ASSET_ID,
                    ),
                    connection,
                )

                deleted = delete_uploaded_asset_with_fallback(
                    asset.asset_id,
                    ["previously-confirmed-world"],
                    connection,
                )

                unchanged_world = get_committed_world(world.world_id, connection)
                self.assertFalse(deleted)
                self.assertEqual(get_asset_metadata(asset.asset_id, connection), asset)
                self.assertTrue(asset_file.exists())
                self.assertEqual(unchanged_world.background_asset_id, asset.asset_id)

    def test_confirmed_builtin_asset_deletion_logs_warning(self) -> None:
        with patched_repo_root() as repo_root:
            with bootstrap_test_database(repo_root) as connection:
                asset = create_asset_metadata(
                    NewAssetMetadata(
                        asset_id="builtin-confirmed-delete-test",
                        asset_type=ASSET_TYPE_IMAGE,
                        display_name="Built-in confirmed delete test",
                        stored_path="app/assets/images/builtin-confirmed-delete.png",
                        is_built_in=True,
                    ),
                    connection,
                )

                with patch("app.storage.asset_deletion.logger") as logger:
                    impact = get_uploaded_asset_deletion_impact(
                        asset.asset_id,
                        connection,
                    )
                    deleted = delete_uploaded_asset_with_fallback(
                        asset.asset_id,
                        [],
                        connection,
                    )

                self.assertIsNone(impact)
                self.assertFalse(deleted)
                self.assertEqual(get_asset_metadata(asset.asset_id, connection), asset)
                self.assertEqual(logger.warning.call_count, 2)

    def test_confirmed_missing_asset_returns_false_and_no_impact(self) -> None:
        with patched_repo_root() as repo_root:
            with bootstrap_test_database(repo_root) as connection:
                impact = get_uploaded_asset_deletion_impact(
                    "missing-asset-id",
                    connection,
                )
                deleted = delete_uploaded_asset_with_fallback(
                    "missing-asset-id",
                    [],
                    connection,
                )

                self.assertIsNone(impact)
                self.assertFalse(deleted)

    def test_confirmed_database_failure_rolls_back_fallback_updates(self) -> None:
        with patched_repo_root() as repo_root:
            with bootstrap_test_database(repo_root) as connection:
                asset = create_uploaded_asset(
                    connection,
                    repo_root,
                    ASSET_TYPE_IMAGE,
                    "user/assets/images/confirmed-database-failure.png",
                )
                asset_file = repo_root / asset.stored_path
                world = create_committed_world(
                    NewCommittedWorld(
                        display_name="Database Failure World",
                        background_asset_id=asset.asset_id,
                        font_asset_id=MAIN_DEFAULT_FONT_ASSET_ID,
                    ),
                    connection,
                )
                failing_connection = FailingDeleteConnection(connection)

                with patch("app.storage.asset_deletion.logger") as logger:
                    with self.assertRaises(sqlite3.Error):
                        delete_uploaded_asset_with_fallback(
                            asset.asset_id,
                            [world.world_id],
                            failing_connection,
                        )

                unchanged_world = get_committed_world(world.world_id, connection)
                self.assertEqual(unchanged_world.background_asset_id, asset.asset_id)
                self.assertEqual(get_asset_metadata(asset.asset_id, connection), asset)
                self.assertTrue(asset_file.exists())
                logger.error.assert_called_once()

    def test_confirmed_file_failure_rolls_back_fallback_updates(self) -> None:
        with patched_repo_root() as repo_root:
            with bootstrap_test_database(repo_root) as connection:
                asset = create_uploaded_asset(
                    connection,
                    repo_root,
                    ASSET_TYPE_FONT,
                    "user/assets/fonts/confirmed-file-failure.ttf",
                )
                world = create_committed_world(
                    NewCommittedWorld(
                        display_name="File Failure World",
                        background_asset_id=MAIN_DEFAULT_BACKGROUND_ASSET_ID,
                        font_asset_id=asset.asset_id,
                    ),
                    connection,
                )

                with (
                    patch("pathlib.Path.unlink", side_effect=OSError),
                    patch("app.storage.asset_deletion.logger") as logger,
                ):
                    with self.assertRaises(OSError):
                        delete_uploaded_asset_with_fallback(
                            asset.asset_id,
                            [world.world_id],
                            connection,
                        )

                unchanged_world = get_committed_world(world.world_id, connection)
                self.assertEqual(unchanged_world.font_asset_id, asset.asset_id)
                self.assertEqual(get_asset_metadata(asset.asset_id, connection), asset)
                logger.error.assert_called_once()

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
