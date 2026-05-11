from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from app.ingestion.parsing.epub import EpubParseError, parse_epub_file
from app.ingestion.parsing.pdf import PdfParseError, parse_pdf_file
from app.ingestion.parsing.txt import TxtParseError, parse_txt_file
from app.logger import get_logger

logger = get_logger()

SOURCE_TYPE_TXT = "txt"
SOURCE_TYPE_EPUB = "epub"
SOURCE_TYPE_PDF = "pdf"

Parser = Callable[[Path], str]

PARSERS_BY_SOURCE_TYPE: dict[str, Parser] = {
    SOURCE_TYPE_TXT: parse_txt_file,
    SOURCE_TYPE_EPUB: parse_epub_file,
    SOURCE_TYPE_PDF: parse_pdf_file,
}

EXPECTED_PARSER_ERRORS = (
    EpubParseError,
    PdfParseError,
    TxtParseError,
    OSError,
)


class UnsupportedSourceTypeError(ValueError):
    pass


@dataclass(frozen=True)
class StagedSource:
    source_file_path: Path
    source_file_type: str


@dataclass(frozen=True)
class ParsedStagedSource:
    source_file_path: Path
    source_file_type: str
    parsed_text: str


@dataclass(frozen=True)
class RoutedStagedSource:
    source: StagedSource
    source_file_type: str
    parser: Parser


def parse_staged_source(source: StagedSource) -> ParsedStagedSource:
    routed_source = route_staged_source(source)
    return parse_routed_staged_source(routed_source)


def parse_staged_source_batch(
    sources: Sequence[StagedSource],
) -> list[ParsedStagedSource]:
    routed_sources = [route_staged_source(source) for source in sources]
    return [parse_routed_staged_source(source) for source in routed_sources]


def route_staged_source(source: StagedSource) -> RoutedStagedSource:
    normalized_source_type = normalize_source_type(source.source_file_type)
    parser = PARSERS_BY_SOURCE_TYPE.get(normalized_source_type)

    if parser is None:
        reject_unsupported_source_type(normalized_source_type)

    logger.debug("Routed staged source to parser: source_type=%s", normalized_source_type)
    return RoutedStagedSource(
        source=source,
        source_file_type=normalized_source_type,
        parser=parser,
    )


def parse_routed_staged_source(source: RoutedStagedSource) -> ParsedStagedSource:
    try:
        parsed_text = source.parser(source.source.source_file_path)
    except EXPECTED_PARSER_ERRORS:
        raise
    except Exception as error:
        logger.error("Unexpected parser router failure.", exc_info=True)
        raise RuntimeError("Unexpected parser router failure.") from error

    return ParsedStagedSource(
        source_file_path=source.source.source_file_path,
        source_file_type=source.source_file_type,
        parsed_text=parsed_text,
    )


def normalize_source_type(source_file_type: str) -> str:
    if type(source_file_type) is not str:
        reject_unsupported_source_type("")

    return source_file_type.strip().lower()


def reject_unsupported_source_type(source_file_type: str) -> NoReturn:
    logger.warning("Unsupported staged source type: %s", source_file_type)
    raise UnsupportedSourceTypeError("Staged source type is not supported.")
