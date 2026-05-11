import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fontTools.ttLib import TTFont

from app.storage.font_upload_validation import (
    FontUploadValidationError,
    MAX_FONT_UPLOAD_SIZE_BYTES,
    validate_uploaded_font_file,
)

TEST_FONT_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "assets"
    / "fonts"
    / "Inter"
    / "Inter-VariableFont_opsz,wght.ttf"
)


class FontUploadValidationTests(unittest.TestCase):
    def test_accepts_valid_ttf_under_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            font_path = Path(temp_directory) / "title-font.ttf"
            write_test_font(font_path)

            validate_uploaded_font_file(font_path, "title-font.ttf")

    def test_accepts_supported_font_suffixes_under_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            font_paths_by_suffix = {
                ".ttf": Path(temp_directory) / "title-font.ttf",
                ".otf": Path(temp_directory) / "title-font.otf",
                ".woff": Path(temp_directory) / "title-font.woff",
                ".woff2": Path(temp_directory) / "title-font.woff2",
            }
            write_test_font(font_paths_by_suffix[".ttf"])
            write_test_font(font_paths_by_suffix[".otf"])
            write_test_font(font_paths_by_suffix[".woff"], flavor="woff")
            write_test_font(font_paths_by_suffix[".woff2"], flavor="woff2")

            for suffix, font_path in font_paths_by_suffix.items():
                with self.subTest(suffix=suffix):
                    validate_uploaded_font_file(font_path, f"title-font{suffix}")

    def test_rejects_unsupported_font_suffix_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            font_path = Path(temp_directory) / "title-font.txt"
            write_test_font(font_path)

            with patch("app.storage.font_upload_validation.logger") as logger:
                with self.assertRaises(FontUploadValidationError):
                    validate_uploaded_font_file(font_path, "title-font.txt")

            logger.warning.assert_called_once()

    def test_rejects_fake_font_content_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            font_path = Path(temp_directory) / "title-font.ttf"
            font_path.write_bytes(b"not a font")

            with patch("app.storage.font_upload_validation.logger") as logger:
                with self.assertRaises(FontUploadValidationError):
                    validate_uploaded_font_file(font_path, "title-font.ttf")

            logger.warning.assert_called_once()

    def test_rejects_oversized_font_before_fonttools_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            font_path = Path(temp_directory) / "title-font.ttf"
            font_path.write_bytes(b"0" * (MAX_FONT_UPLOAD_SIZE_BYTES + 1))

            with (
                patch("app.storage.font_upload_validation.get_fonttools_loaders") as loaders,
                patch("app.storage.font_upload_validation.logger") as logger,
            ):
                with self.assertRaises(FontUploadValidationError):
                    validate_uploaded_font_file(font_path, "title-font.ttf")

            loaders.assert_not_called()
            logger.warning.assert_called_once()

    def test_unexpected_size_failure_logs_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            font_path = Path(temp_directory) / "missing.ttf"

            with patch("app.storage.font_upload_validation.logger") as logger:
                with self.assertRaises(OSError):
                    validate_uploaded_font_file(font_path, "missing.ttf")

            logger.error.assert_called_once()

    def test_missing_fonttools_dependency_logs_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            font_path = Path(temp_directory) / "title-font.ttf"
            write_test_font(font_path)

            with (
                patch(
                    "app.storage.font_upload_validation.get_fonttools_loaders",
                    side_effect=ImportError("fontTools missing"),
                ),
                patch("app.storage.font_upload_validation.logger") as logger,
            ):
                with self.assertRaises(ImportError):
                    validate_uploaded_font_file(font_path, "title-font.ttf")

            logger.error.assert_called_once()

    def test_unexpected_fonttools_failure_logs_error(self) -> None:
        class FakeTTLibError(Exception):
            pass

        with tempfile.TemporaryDirectory() as temp_directory:
            font_path = Path(temp_directory) / "title-font.ttf"
            write_test_font(font_path)
            broken_loader = Mock(side_effect=RuntimeError("fontTools failed"))

            with (
                patch(
                    "app.storage.font_upload_validation.get_fonttools_loaders",
                    return_value=(broken_loader, FakeTTLibError),
                ),
                patch("app.storage.font_upload_validation.logger") as logger,
            ):
                with self.assertRaises(RuntimeError):
                    validate_uploaded_font_file(font_path, "title-font.ttf")

            logger.error.assert_called_once()


def write_test_font(font_path: Path, flavor: str | None = None) -> None:
    font_path.parent.mkdir(parents=True, exist_ok=True)
    if flavor is None:
        shutil.copy2(TEST_FONT_PATH, font_path)
        return

    font = TTFont(TEST_FONT_PATH)
    try:
        font.flavor = flavor
        font.save(font_path)
    finally:
        font.close()


if __name__ == "__main__":
    unittest.main()
