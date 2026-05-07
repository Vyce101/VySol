import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from app.draft_worlds.registry import DraftWorldRegistry
from app.storage.world_folders import (
    WorldFolderValidationError,
    create_committed_world_folder,
    resolve_world_directory,
    resolve_world_sources_directory,
)


class WorldFolderBootstrapTests(unittest.TestCase):
    def test_resolves_world_directory_under_user_worlds(self) -> None:
        with patched_repo_root() as repo_root:
            world_id = str(uuid4())

            world_directory = resolve_world_directory(world_id)

            self.assertEqual(world_directory, repo_root / "user" / "worlds" / world_id)

    def test_resolves_sources_directory_inside_world_directory(self) -> None:
        with patched_repo_root() as repo_root:
            world_id = str(uuid4())

            sources_directory = resolve_world_sources_directory(world_id)

            self.assertEqual(
                sources_directory,
                repo_root / "user" / "worlds" / world_id / "sources",
            )

    def test_creates_committed_world_folder_and_sources_folder(self) -> None:
        with patched_repo_root() as repo_root:
            world_id = str(uuid4())

            created_directory = create_committed_world_folder(world_id)

            self.assertEqual(created_directory, repo_root / "user" / "worlds" / world_id)
            self.assertTrue(created_directory.is_dir())
            self.assertTrue((created_directory / "sources").is_dir())

    def test_path_helpers_accept_only_world_id_argument(self) -> None:
        helper_functions = (
            resolve_world_directory,
            resolve_world_sources_directory,
            create_committed_world_folder,
        )

        for helper_function in helper_functions:
            with self.subTest(helper_function=helper_function.__name__):
                self.assertEqual(
                    tuple(inspect.signature(helper_function).parameters),
                    ("world_id",),
                )

    def test_rejects_display_name_as_world_id_and_creates_no_folder(self) -> None:
        with patched_repo_root() as repo_root:
            with self.assertRaises(WorldFolderValidationError):
                resolve_world_directory("Naruto")

            self.assertFalse((repo_root / "user" / "worlds").exists())

    def test_rejects_invalid_world_id_before_creating_folders(self) -> None:
        with patched_repo_root() as repo_root:
            with self.assertRaises(WorldFolderValidationError):
                create_committed_world_folder("../not-a-world-id")

            self.assertFalse((repo_root / "user" / "worlds").exists())

    def test_logs_folder_creation_failure_and_reraises(self) -> None:
        with patched_repo_root() as repo_root:
            worlds_path = repo_root / "user" / "worlds"
            worlds_path.parent.mkdir(parents=True)
            worlds_path.write_text("not a folder", encoding="utf-8")

            with patch("app.storage.world_folders.logger") as logger:
                with self.assertRaises(OSError):
                    create_committed_world_folder(str(uuid4()))

            logger.error.assert_called_once_with(
                "Failed to create committed world folder.",
                exc_info=True,
            )

    def test_draft_world_creation_does_not_create_worlds_folder(self) -> None:
        with patched_repo_root() as repo_root:
            registry = DraftWorldRegistry()

            registry.create_draft_world()

            self.assertFalse((repo_root / "user" / "worlds").exists())


class patched_repo_root:
    def __enter__(self) -> Path:
        self._temp_directory = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._temp_directory.name)
        self._patcher = patch("app.storage.paths.REPO_ROOT", self.repo_root)
        self._patcher.start()
        return self.repo_root

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self._patcher.stop()
        self._temp_directory.cleanup()


if __name__ == "__main__":
    unittest.main()
