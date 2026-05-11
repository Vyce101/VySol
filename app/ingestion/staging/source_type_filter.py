from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.logger import get_logger

logger = get_logger()

SOURCE_TYPE_TXT = "txt"
SOURCE_TYPE_EPUB = "epub"
SOURCE_TYPE_PDF = "pdf"
MISSING_SOURCE_TYPE = "missing"

SUPPORTED_SOURCE_TYPES_BY_SUFFIX = {
    ".txt": SOURCE_TYPE_TXT,
    ".epub": SOURCE_TYPE_EPUB,
    ".pdf": SOURCE_TYPE_PDF,
}

UNSUPPORTED_SOURCE_TYPE_MESSAGE = (
    "Unsupported source type. Supported source types: .txt, .epub, .pdf."
)


@dataclass(frozen=True)
class SourceStagingItem:
    source_file_path: Path
    source_file_type: str
    is_valid: bool
    error_message: str | None


def build_source_staging_list(
    source_file_paths: Sequence[Path],
) -> list[SourceStagingItem]:
    try:
        return [
            build_source_staging_item(source_file_path)
            for source_file_path in source_file_paths
        ]
    except Exception as error:
        logger.error("Unexpected source type filter failure.", exc_info=True)
        raise RuntimeError("Unexpected source type filter failure.") from error


def build_source_staging_item(source_file_path: Path) -> SourceStagingItem:
    normalized_source_path = Path(source_file_path)
    source_suffix = normalized_source_path.suffix.lower()
    source_file_type = SUPPORTED_SOURCE_TYPES_BY_SUFFIX.get(source_suffix)

    if source_file_type is not None:
        return SourceStagingItem(
            source_file_path=normalized_source_path,
            source_file_type=source_file_type,
            is_valid=True,
            error_message=None,
        )

    unsupported_source_type = get_unsupported_source_type(source_suffix)
    logger.warning(
        "Unsupported staged source type selected: source_type=%s",
        unsupported_source_type,
    )
    return SourceStagingItem(
        source_file_path=normalized_source_path,
        source_file_type=unsupported_source_type,
        is_valid=False,
        error_message=UNSUPPORTED_SOURCE_TYPE_MESSAGE,
    )


def get_unsupported_source_type(source_suffix: str) -> str:
    if not source_suffix:
        return MISSING_SOURCE_TYPE

    return source_suffix.removeprefix(".")


def can_start_ingestion(staged_sources: Sequence[SourceStagingItem]) -> bool:
    return bool(staged_sources) and all(source.is_valid for source in staged_sources)
