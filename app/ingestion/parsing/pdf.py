from pathlib import Path
from typing import NoReturn

import pymupdf

from app.logger import get_logger

logger = get_logger()

PDF_FILE_TYPE = "pdf"
PDF_TEXT_OUTPUT = "text"
PAGE_JOINER = "\n\n"


class PdfParseError(ValueError):
    pass


def parse_pdf_file(source_file_path: Path) -> str:
    document = read_pdf_document(source_file_path)

    try:
        page_count = len(document)
        page_texts = extract_page_texts(document)
    except PdfParseError:
        raise
    except Exception as error:
        logger.error("Unexpected PDF text extraction failure.", exc_info=True)
        raise PdfParseError("PDF source text could not be extracted.") from error
    finally:
        document.close()

    parsed_text = PAGE_JOINER.join(page_texts)

    if has_usable_text(parsed_text):
        logger.info(
            "Parsed PDF source: page_count=%s text_page_count=%s character_count=%s",
            page_count,
            len(page_texts),
            len(parsed_text),
        )
        return parsed_text

    reject_pdf_without_usable_text()


def read_pdf_document(source_file_path: Path) -> pymupdf.Document:
    if not source_file_path.exists():
        reject_unavailable_pdf("missing")

    if not source_file_path.is_file():
        reject_unavailable_pdf("not_file")

    try:
        return pymupdf.open(str(source_file_path), filetype=PDF_FILE_TYPE)
    except pymupdf.FileNotFoundError as error:
        reject_unavailable_pdf("missing", error)
    except OSError as error:
        reject_unavailable_pdf("unreadable", error)
    except (RuntimeError, ValueError) as error:
        logger.error("Unexpected PDF file read failure.", exc_info=True)
        raise PdfParseError("PDF source could not be read.") from error


def extract_page_texts(document: pymupdf.Document) -> list[str]:
    page_texts: list[str] = []

    for page in document:
        page_text = extract_page_text(page)

        if has_usable_text(page_text):
            page_texts.append(page_text.strip())

    return page_texts


def extract_page_text(page: pymupdf.Page) -> str:
    try:
        return page.get_text(PDF_TEXT_OUTPUT, sort=True)
    except Exception as error:
        logger.error("Unexpected PDF text extraction failure.", exc_info=True)
        raise PdfParseError("PDF source text could not be extracted.") from error


def has_usable_text(text: str) -> bool:
    return bool(text.strip())


def reject_pdf_without_usable_text() -> NoReturn:
    logger.warning("Rejected PDF source with no usable text.")
    raise PdfParseError("PDF source did not contain usable text.")


def reject_unavailable_pdf(reason: str, error: Exception | None = None) -> NoReturn:
    logger.warning("Rejected unavailable PDF source: reason=%s", reason)
    raise PdfParseError("PDF source could not be read.") from error
