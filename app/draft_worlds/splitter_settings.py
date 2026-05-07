from dataclasses import dataclass
from typing import NoReturn

from app.logger import get_logger

DEFAULT_CHUNK_SIZE = 4000
DEFAULT_MAX_LOOKBACK_SIZE = 1000
DEFAULT_OVERLAP_SIZE = 400
CURRENT_SPLITTER_VERSION = "1"

logger = get_logger()


class SplitterSettingsValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SplitterSettings:
    chunk_size: int
    max_lookback_size: int
    overlap_size: int
    splitter_version: str


def create_default_splitter_settings() -> SplitterSettings:
    return SplitterSettings(
        chunk_size=DEFAULT_CHUNK_SIZE,
        max_lookback_size=DEFAULT_MAX_LOOKBACK_SIZE,
        overlap_size=DEFAULT_OVERLAP_SIZE,
        splitter_version=CURRENT_SPLITTER_VERSION,
    )


def validate_splitter_settings(
    splitter_settings: SplitterSettings,
) -> SplitterSettings:
    try:
        splitter_version = getattr(splitter_settings, "splitter_version", None)
        logger.debug(
            "Validating splitter settings: chunk_size=%s max_lookback_size=%s "
            "overlap_size=%s splitter_version=%s",
            splitter_settings.chunk_size,
            splitter_settings.max_lookback_size,
            splitter_settings.overlap_size,
            splitter_version,
        )
        require_whole_number(splitter_settings.chunk_size, "Chunk size")
        require_whole_number(
            splitter_settings.max_lookback_size,
            "Max lookback size",
        )
        require_whole_number(splitter_settings.overlap_size, "Overlap size")
        require_non_empty_text(splitter_version, "Splitter version")
        require_minimum_chunk_size(splitter_settings.chunk_size)
        require_minimum_max_lookback_size(splitter_settings.max_lookback_size)
        require_max_lookback_less_than_chunk_size(
            splitter_settings.max_lookback_size,
            splitter_settings.chunk_size,
        )
        require_minimum_overlap_size(splitter_settings.overlap_size)
    except SplitterSettingsValidationError:
        raise
    except Exception:
        logger.error("Unexpected splitter settings validation failure.", exc_info=True)
        raise

    return splitter_settings


def require_whole_number(value: int, field_name: str) -> None:
    if type(value) is int:
        return

    reject_invalid_splitter_settings(f"{field_name} must be a whole number.")


def require_non_empty_text(value: str | None, field_name: str) -> None:
    if type(value) is str and value.strip():
        return

    reject_invalid_splitter_settings(f"{field_name} is required.")


def require_minimum_chunk_size(chunk_size: int) -> None:
    if chunk_size >= 1:
        return

    reject_invalid_splitter_settings("Chunk size must be positive.")


def require_minimum_max_lookback_size(max_lookback_size: int) -> None:
    if max_lookback_size >= 0:
        return

    reject_invalid_splitter_settings("Max lookback size must not be negative.")


def require_max_lookback_less_than_chunk_size(
    max_lookback_size: int,
    chunk_size: int,
) -> None:
    if max_lookback_size < chunk_size:
        return

    reject_invalid_splitter_settings(
        "Max lookback size must be less than chunk size."
    )


def require_minimum_overlap_size(overlap_size: int) -> None:
    if overlap_size >= 0:
        return

    reject_invalid_splitter_settings("Overlap size must not be negative.")


def reject_invalid_splitter_settings(message: str) -> NoReturn:
    logger.warning("Invalid splitter settings rejected: %s", message)
    raise SplitterSettingsValidationError(message)
