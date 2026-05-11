from collections.abc import Callable
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import NoReturn

from app.logger import get_logger

logger = get_logger()

MAX_FONT_UPLOAD_SIZE_BYTES = 3 * 1024 * 1024
SUPPORTED_FONT_SUFFIXES = frozenset({".otf", ".ttf", ".woff", ".woff2"})


class FontUploadValidationError(ValueError):
    pass


def validate_uploaded_font_file(source_file_path: Path, original_filename: str) -> None:
    validate_font_file_type(original_filename)
    validate_font_file_size(source_file_path)
    verify_font_content(source_file_path)
    logger.info("Accepted font upload.")


def validate_font_file_type(original_filename: str) -> None:
    filename = get_filename_component(original_filename)
    suffix = Path(filename).suffix.lower()

    if suffix not in SUPPORTED_FONT_SUFFIXES:
        reject_font_upload("Rejected unsupported font upload file type.")


def validate_font_file_size(source_file_path: Path) -> None:
    try:
        file_size = source_file_path.stat().st_size
    except OSError:
        logger.error("Failed to read uploaded font file size.", exc_info=True)
        raise

    if file_size > MAX_FONT_UPLOAD_SIZE_BYTES:
        reject_font_upload("Rejected oversized font upload.")


def verify_font_content(source_file_path: Path) -> None:
    try:
        TTFont, TTLibError = get_fonttools_loaders()
    except ImportError:
        logger.error("Font validation dependency is unavailable.", exc_info=True)
        raise

    try:
        with TTFont(
            source_file_path,
            lazy=False,
            recalcBBoxes=False,
            recalcTimestamp=False,
        ) as font:
            for table_tag in font.keys():
                font[table_tag]
            font.getGlyphOrder()
    except (OSError, TTLibError):
        reject_font_upload("Rejected invalid font upload content.")
    except Exception:
        logger.error("Unexpected font upload validation failure.", exc_info=True)
        raise


def get_fonttools_loaders() -> tuple[Callable[..., object], type[Exception]]:
    from fontTools.ttLib import TTFont, TTLibError

    return TTFont, TTLibError


def get_filename_component(original_filename: str) -> str:
    posix_name = PurePosixPath(original_filename).name
    return PureWindowsPath(posix_name).name


def reject_font_upload(message: str) -> NoReturn:
    logger.warning(message)
    raise FontUploadValidationError(message)
