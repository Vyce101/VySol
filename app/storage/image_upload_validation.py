from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import NoReturn
import warnings

from PIL import Image, UnidentifiedImageError

from app.logger import get_logger

logger = get_logger()

MAX_IMAGE_UPLOAD_SIZE_BYTES = 3 * 1024 * 1024

IMAGE_FORMATS_BY_SUFFIX = {
    ".jpeg": "JPEG",
    ".jpg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
}


class ImageUploadValidationError(ValueError):
    pass


def validate_uploaded_image_file(source_file_path: Path, original_filename: str) -> None:
    expected_format = get_expected_image_format(original_filename)
    validate_image_file_size(source_file_path)
    verify_image_content(source_file_path, expected_format)


def get_expected_image_format(original_filename: str) -> str:
    filename = get_filename_component(original_filename)
    suffix = Path(filename).suffix.lower()
    expected_format = IMAGE_FORMATS_BY_SUFFIX.get(suffix)

    if expected_format is None:
        return reject_image_upload("Rejected unsupported image upload file type.")

    return expected_format


def validate_image_file_size(source_file_path: Path) -> None:
    try:
        file_size = source_file_path.stat().st_size
    except OSError:
        logger.error("Failed to read uploaded image file size.", exc_info=True)
        raise

    if file_size > MAX_IMAGE_UPLOAD_SIZE_BYTES:
        reject_image_upload("Rejected oversized image upload.")


def verify_image_content(source_file_path: Path, expected_format: str) -> None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source_file_path, formats=(expected_format,)) as image:
                image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombWarning):
        reject_image_upload("Rejected invalid image upload content.")
    except Exception:
        logger.error("Unexpected image upload validation failure.", exc_info=True)
        raise


def get_filename_component(original_filename: str) -> str:
    posix_name = PurePosixPath(original_filename).name
    return PureWindowsPath(posix_name).name


def reject_image_upload(message: str) -> NoReturn:
    logger.warning(message)
    raise ImageUploadValidationError(message)
