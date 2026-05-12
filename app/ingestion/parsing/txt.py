from pathlib import Path
from typing import NoReturn

from app.logger import get_logger

logger = get_logger()

BOM_PREFIX_READ_SIZE = 4

TXT_ENCODINGS_BY_BOM = (
    (b"\xff\xfe\x00\x00", "utf-32"),
    (b"\x00\x00\xfe\xff", "utf-32"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
)

DEFAULT_TXT_ENCODING = "utf-8"


class TxtParseError(ValueError):
    pass


def parse_txt_file(source_file_path: Path) -> str:
    try:
        encoding = choose_txt_encoding(source_file_path)
    except OSError as error:
        reject_unavailable_txt(error)

    try:
        parsed_text = read_txt_text(source_file_path, encoding)
    except UnicodeDecodeError as error:
        reject_unreadable_txt(encoding, error)
    except OSError as error:
        reject_unavailable_txt(error)

    logger.info(
        "Parsed TXT source: encoding=%s character_count=%s",
        encoding,
        len(parsed_text),
    )
    return parsed_text


def choose_txt_encoding(source_file_path: Path) -> str:
    with source_file_path.open("rb") as source_file:
        file_prefix = source_file.read(BOM_PREFIX_READ_SIZE)

    for bom, encoding in TXT_ENCODINGS_BY_BOM:
        if file_prefix.startswith(bom):
            return encoding

    return DEFAULT_TXT_ENCODING


def read_txt_text(source_file_path: Path, encoding: str) -> str:
    with source_file_path.open(
        "r",
        encoding=encoding,
        errors="strict",
        newline="",
    ) as source_file:
        return source_file.read()


def reject_unreadable_txt(encoding: str, error: UnicodeDecodeError) -> NoReturn:
    logger.warning("Rejected unreadable TXT source: encoding=%s", encoding)
    raise TxtParseError("TXT source could not be decoded as clean supported text.") from error


def reject_unavailable_txt(error: OSError | None = None) -> NoReturn:
    logger.warning(
        "Rejected unavailable TXT source: error_type=%s",
        type(error).__name__ if error is not None else "OSError",
    )
    raise TxtParseError("TXT source could not be read.") from error
