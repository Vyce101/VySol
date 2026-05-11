from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.storage.asset_files import (
    ASSET_STORAGE_DIRECTORIES,
    resolve_asset_file_path,
    store_uploaded_asset_file,
)
from app.storage.assets import (
    ASSET_TYPE_FONT,
    ASSET_TYPE_IMAGE,
    NewAssetMetadata,
    create_asset_metadata,
)
from app.storage.database import bootstrap_global_database, close_global_connection


class AssetFileStorageTests(unittest.TestCase):
    def tearDown(self) -> None:
        close_global_connection()

    def test_stores_uploaded_image_under_safe_internal_path(self) -> None:
        with patched_asset_storage() as storage:
            with bootstrap_test_database(storage.repo_root) as connection:
                source_file = storage.repo_root / "uploads" / "portrait upload.png"
                source_file.parent.mkdir(parents=True)
                write_test_image(source_file)

                asset = store_uploaded_asset_file(
                    ASSET_TYPE_IMAGE,
                    source_file,
                    "portrait upload.png",
                    connection,
                )

                stored_file = storage.image_directory / f"{asset.asset_id}.png"
                self.assertTrue(stored_file.exists())
                self.assertEqual(stored_file.read_bytes(), source_file.read_bytes())
                self.assertEqual(
                    asset.stored_path,
                    f"user/assets/images/{asset.asset_id}.png",
                )
                self.assertNotIn("portrait upload", asset.stored_path)
                self.assertEqual(asset.display_name, "portrait upload")
                self.assertEqual(asset.original_filename, "portrait upload.png")

    def test_stores_uploaded_font_under_safe_internal_path(self) -> None:
        with patched_asset_storage() as storage:
            with bootstrap_test_database(storage.repo_root) as connection:
                source_file = storage.repo_root / "uploads" / "title-font.ttf"
                source_file.parent.mkdir(parents=True)
                source_file.write_bytes(b"font bytes")

                asset = store_uploaded_asset_file(
                    ASSET_TYPE_FONT,
                    source_file,
                    "title-font.ttf",
                    connection,
                )

                stored_file = storage.font_directory / f"{asset.asset_id}.ttf"
                self.assertTrue(stored_file.exists())
                self.assertEqual(stored_file.read_bytes(), b"font bytes")
                self.assertEqual(
                    asset.stored_path,
                    f"user/assets/fonts/{asset.asset_id}.ttf",
                )

    def test_duplicate_display_names_are_allowed_for_different_files(self) -> None:
        with patched_asset_storage() as storage:
            with bootstrap_test_database(storage.repo_root) as connection:
                first_file = storage.repo_root / "uploads" / "duplicate-a.png"
                second_file = storage.repo_root / "uploads" / "duplicate-b.png"
                first_file.parent.mkdir(parents=True)
                write_test_image(first_file, color=(255, 0, 0))
                write_test_image(second_file, color=(0, 0, 255))

                first_asset = store_uploaded_asset_file(
                    ASSET_TYPE_IMAGE,
                    first_file,
                    "duplicate.png",
                    connection,
                )
                second_asset = store_uploaded_asset_file(
                    ASSET_TYPE_IMAGE,
                    second_file,
                    "duplicate.png",
                    connection,
                )

                self.assertNotEqual(first_asset.asset_id, second_asset.asset_id)
                self.assertEqual(first_asset.display_name, "duplicate")
                self.assertEqual(second_asset.display_name, "duplicate")

    def test_resolves_asset_file_path_by_asset_id(self) -> None:
        with patched_asset_storage() as storage:
            with bootstrap_test_database(storage.repo_root) as connection:
                source_file = storage.repo_root / "uploads" / "resolved.png"
                source_file.parent.mkdir(parents=True)
                write_test_image(source_file)
                asset = store_uploaded_asset_file(
                    ASSET_TYPE_IMAGE,
                    source_file,
                    "resolved.png",
                    connection,
                )

                resolved_path = resolve_asset_file_path(asset.asset_id, connection)

                self.assertEqual(
                    resolved_path,
                    storage.image_directory / f"{asset.asset_id}.png",
                )

    def test_rejects_unsafe_stored_path_without_logging_raw_path(self) -> None:
        with patched_asset_storage() as storage:
            with bootstrap_test_database(storage.repo_root) as connection:
                asset = create_asset_metadata(
                    NewAssetMetadata(
                        asset_id="unsafe-path-asset",
                        asset_type=ASSET_TYPE_IMAGE,
                        display_name="Unsafe",
                        stored_path="../very-secret-user-path.png",
                        is_built_in=False,
                        file_hash="sha256:unsafe-path",
                    ),
                    connection,
                )

                with patch("app.storage.asset_files.logger") as logger:
                    resolved_path = resolve_asset_file_path(asset.asset_id, connection)

                self.assertIsNone(resolved_path)
                logger.error.assert_called()
                logged_text = get_logged_text(logger)
                self.assertNotIn("very-secret-user-path", logged_text)

    def test_copy_failure_logs_error_and_reraises(self) -> None:
        with patched_asset_storage() as storage:
            with bootstrap_test_database(storage.repo_root) as connection:
                source_file = storage.repo_root / "uploads" / "copy-failure.png"
                source_file.parent.mkdir(parents=True)
                write_test_image(source_file)

                with (
                    patch("app.storage.asset_files.shutil.copy2", side_effect=OSError),
                    patch("app.storage.asset_files.logger") as logger,
                ):
                    with self.assertRaises(OSError):
                        store_uploaded_asset_file(
                            ASSET_TYPE_IMAGE,
                            source_file,
                            "copy-failure.png",
                            connection,
                        )

                logger.error.assert_called_once()

    def test_unsupported_filename_pattern_logs_warning(self) -> None:
        with patched_asset_storage() as storage:
            with bootstrap_test_database(storage.repo_root) as connection:
                source_file = storage.repo_root / "uploads" / "portrait.png"
                source_file.parent.mkdir(parents=True)
                write_test_image(source_file)

                with patch("app.storage.asset_files.logger") as logger:
                    asset = store_uploaded_asset_file(
                        ASSET_TYPE_IMAGE,
                        source_file,
                        r"unsafe\Portrait.PNG",
                        connection,
                    )

                logger.warning.assert_called()
                self.assertEqual(asset.display_name, "Portrait")
                self.assertEqual(asset.original_filename, r"unsafe\Portrait.PNG")
                self.assertEqual(
                    asset.stored_path,
                    f"user/assets/images/{asset.asset_id}.png",
                )

    def test_rejects_fake_image_before_copying_or_metadata(self) -> None:
        with patched_asset_storage() as storage:
            with bootstrap_test_database(storage.repo_root) as connection:
                source_file = storage.repo_root / "uploads" / "fake.png"
                source_file.parent.mkdir(parents=True)
                source_file.write_bytes(b"not really an image")

                with self.assertRaises(ValueError):
                    store_uploaded_asset_file(
                        ASSET_TYPE_IMAGE,
                        source_file,
                        "fake.png",
                        connection,
                    )

                stored_files = list(storage.image_directory.glob("*"))
                asset_count = connection.execute(
                    """
                    SELECT COUNT(*) AS asset_count
                    FROM assets
                    WHERE is_built_in = 0
                    """
                ).fetchone()["asset_count"]

                self.assertEqual(stored_files, [])
                self.assertEqual(asset_count, 0)

    def test_missing_font_display_name_uses_fallback_and_logs_warning(self) -> None:
        with patched_asset_storage() as storage:
            with bootstrap_test_database(storage.repo_root) as connection:
                source_file = storage.repo_root / "uploads" / "empty-name"
                source_file.parent.mkdir(parents=True)
                source_file.write_bytes(b"font bytes")

                with patch("app.storage.asset_files.logger") as logger:
                    asset = store_uploaded_asset_file(
                        ASSET_TYPE_FONT,
                        source_file,
                        "",
                        connection,
                    )

                logger.warning.assert_called()
                self.assertEqual(asset.display_name, "Uploaded font")


def get_logged_text(logger: object) -> str:
    return " ".join(
        str(value)
        for call in logger.method_calls
        for value in call.args
    )


def write_test_image(
    image_path: Path,
    color: tuple[int, int, int] = (255, 255, 255),
) -> None:
    with Image.new("RGB", (2, 2), color=color) as image:
        image.save(image_path, format="PNG")


@contextmanager
def patched_asset_storage() -> Iterator["PatchedAssetStorage"]:
    with tempfile.TemporaryDirectory() as temp_directory:
        repo_root = Path(temp_directory) / "repo"
        image_directory = repo_root / "user" / "assets" / "images"
        font_directory = repo_root / "user" / "assets" / "fonts"
        storage = PatchedAssetStorage(repo_root, image_directory, font_directory)

        with (
            patch("app.storage.asset_files.REPO_ROOT", repo_root),
            patch.dict(
                ASSET_STORAGE_DIRECTORIES,
                {
                    ASSET_TYPE_IMAGE: lambda: image_directory,
                    ASSET_TYPE_FONT: lambda: font_directory,
                },
            ),
        ):
            yield storage


@contextmanager
def bootstrap_test_database(repo_root: Path) -> Iterator[sqlite3.Connection]:
    database_path = repo_root / "user" / "data" / "app.sqlite"
    try:
        yield bootstrap_global_database(database_path)
    finally:
        close_global_connection()


class PatchedAssetStorage:
    def __init__(
        self,
        repo_root: Path,
        image_directory: Path,
        font_directory: Path,
    ) -> None:
        self.repo_root = repo_root
        self.image_directory = image_directory
        self.font_directory = font_directory


if __name__ == "__main__":
    unittest.main()
