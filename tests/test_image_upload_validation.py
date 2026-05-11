import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.storage.image_upload_validation import (
    ImageUploadValidationError,
    MAX_IMAGE_UPLOAD_SIZE_BYTES,
    validate_uploaded_image_file,
)


class ImageUploadValidationTests(unittest.TestCase):
    def test_accepts_valid_png_under_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            image_path = Path(temp_directory) / "background.png"
            write_test_image(image_path, "PNG")

            validate_uploaded_image_file(image_path, "background.png")

    def test_accepts_valid_jpg_and_jpeg_under_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            jpg_path = Path(temp_directory) / "background.jpg"
            jpeg_path = Path(temp_directory) / "background.jpeg"
            write_test_image(jpg_path, "JPEG")
            write_test_image(jpeg_path, "JPEG")

            validate_uploaded_image_file(jpg_path, "background.jpg")
            validate_uploaded_image_file(jpeg_path, "background.jpeg")

    def test_accepts_valid_webp_under_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            image_path = Path(temp_directory) / "background.webp"
            write_test_image(image_path, "WEBP")

            validate_uploaded_image_file(image_path, "background.webp")

    def test_rejects_unsupported_image_suffix_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            image_path = Path(temp_directory) / "background.gif"
            write_test_image(image_path, "PNG")

            with patch("app.storage.image_upload_validation.logger") as logger:
                with self.assertRaises(ImageUploadValidationError):
                    validate_uploaded_image_file(image_path, "background.gif")

            logger.warning.assert_called_once()

    def test_rejects_fake_image_content_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            image_path = Path(temp_directory) / "background.png"
            image_path.write_bytes(b"not an image")

            with patch("app.storage.image_upload_validation.logger") as logger:
                with self.assertRaises(ImageUploadValidationError):
                    validate_uploaded_image_file(image_path, "background.png")

            logger.warning.assert_called_once()

    def test_rejects_mismatched_image_content_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            image_path = Path(temp_directory) / "background.jpg"
            write_test_image(image_path, "PNG")

            with patch("app.storage.image_upload_validation.logger") as logger:
                with self.assertRaises(ImageUploadValidationError):
                    validate_uploaded_image_file(image_path, "background.jpg")

            logger.warning.assert_called_once()

    def test_rejects_oversized_image_before_pillow_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            image_path = Path(temp_directory) / "background.png"
            image_path.write_bytes(b"0" * (MAX_IMAGE_UPLOAD_SIZE_BYTES + 1))

            with (
                patch("app.storage.image_upload_validation.Image.open") as image_open,
                patch("app.storage.image_upload_validation.logger") as logger,
            ):
                with self.assertRaises(ImageUploadValidationError):
                    validate_uploaded_image_file(image_path, "background.png")

            image_open.assert_not_called()
            logger.warning.assert_called_once()

    def test_unexpected_size_failure_logs_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            image_path = Path(temp_directory) / "missing.png"

            with patch("app.storage.image_upload_validation.logger") as logger:
                with self.assertRaises(OSError):
                    validate_uploaded_image_file(image_path, "missing.png")

            logger.error.assert_called_once()

    def test_unexpected_pillow_failure_logs_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            image_path = Path(temp_directory) / "background.png"
            write_test_image(image_path, "PNG")

            with (
                patch(
                    "app.storage.image_upload_validation.Image.open",
                    side_effect=RuntimeError("pillow failed"),
                ),
                patch("app.storage.image_upload_validation.logger") as logger,
            ):
                with self.assertRaises(RuntimeError):
                    validate_uploaded_image_file(image_path, "background.png")

            logger.error.assert_called_once()


def write_test_image(image_path: Path, image_format: str) -> None:
    with Image.new("RGB", (2, 2), color=(255, 255, 255)) as image:
        image.save(image_path, format=image_format)


if __name__ == "__main__":
    unittest.main()
