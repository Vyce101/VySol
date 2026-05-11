import zipfile
from pathlib import Path
from typing import Any, NoReturn

from bs4 import BeautifulSoup
from bs4.element import NavigableString, PageElement, Tag
from ebooklib import ITEM_DOCUMENT, epub

from app.logger import get_logger

logger = get_logger()

EPUB_READ_OPTIONS = {"ignore_ncx": True}
HTML_PARSER = "html.parser"
DOCUMENT_JOINER = "\n\n"
BLOCK_JOINER = "\n"
INLINE_JOINER = " "
TABLE_CELL_JOINER = " | "

NON_READABLE_TAG_NAMES = (
    "head",
    "metadata",
    "nav",
    "noscript",
    "script",
    "style",
    "svg",
)

TEXT_BLOCK_TAG_NAMES = (
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "li",
    "blockquote",
    "figcaption",
    "caption",
    "pre",
    "td",
    "th",
)

TABLE_CELL_TAG_NAMES = ("td", "th")


class EpubParseError(ValueError):
    pass


def parse_epub_file(source_file_path: Path) -> str:
    book = read_epub_book(source_file_path)
    document_texts = extract_spine_document_texts(book)
    parsed_text = DOCUMENT_JOINER.join(document_texts)

    if has_usable_text(parsed_text):
        logger.info(
            "Parsed EPUB source: spine_document_count=%s character_count=%s",
            len(document_texts),
            len(parsed_text),
        )
        return parsed_text

    reject_epub_without_usable_text()


def read_epub_book(source_file_path: Path) -> epub.EpubBook:
    try:
        return epub.read_epub(str(source_file_path), options=EPUB_READ_OPTIONS)
    except (epub.EpubException, zipfile.BadZipFile) as error:
        reject_malformed_epub(error)
    except OSError:
        logger.error("Unexpected EPUB file read failure.", exc_info=True)
        raise
    except Exception as error:
        logger.error("Unexpected EPUB read failure.", exc_info=True)
        raise EpubParseError("EPUB source could not be read.") from error


def extract_spine_document_texts(book: epub.EpubBook) -> list[str]:
    document_texts: list[str] = []

    for spine_entry in book.spine:
        item = get_spine_document_item(book, spine_entry)

        if item is None:
            continue

        document_text = extract_document_text(item.get_content())

        if has_usable_text(document_text):
            document_texts.append(document_text)

    return document_texts


def get_spine_document_item(
    book: epub.EpubBook,
    spine_entry: Any,
) -> epub.EpubItem | None:
    item_id = get_spine_item_id(spine_entry)

    if not item_id:
        reject_malformed_epub_spine()

    item = book.get_item_with_id(item_id)

    if item is None:
        reject_malformed_epub_spine()

    if item.get_type() != ITEM_DOCUMENT:
        return None

    return item


def get_spine_item_id(spine_entry: Any) -> str:
    if type(spine_entry) is str:
        return spine_entry

    if not spine_entry:
        return ""

    return str(spine_entry[0])


def extract_document_text(document_content: bytes) -> str:
    try:
        soup = BeautifulSoup(document_content, HTML_PARSER)
        remove_non_readable_tags(soup)
        root = soup.body if soup.body is not None else soup
        text_blocks = extract_text_blocks(root)
    except Exception as error:
        logger.error("Unexpected EPUB HTML extraction failure.", exc_info=True)
        raise EpubParseError("EPUB source HTML could not be parsed.") from error

    return BLOCK_JOINER.join(text_blocks)


def remove_non_readable_tags(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(NON_READABLE_TAG_NAMES):
        tag.decompose()


def extract_text_blocks(container: Tag | BeautifulSoup) -> list[str]:
    text_blocks: list[str] = []
    inline_fragments: list[str] = []

    for child in container.children:
        if is_inline_text(child):
            add_inline_fragment(inline_fragments, child)
            continue

        if not isinstance(child, Tag):
            continue

        flush_inline_fragments(text_blocks, inline_fragments)
        text_blocks.extend(extract_tag_text_blocks(child))

    flush_inline_fragments(text_blocks, inline_fragments)
    return text_blocks


def extract_tag_text_blocks(tag: Tag) -> list[str]:
    if tag.name in TEXT_BLOCK_TAG_NAMES:
        text = get_block_text(tag)
        return [text] if has_usable_text(text) else []

    if tag.name == "tr":
        row_text = get_table_row_text(tag)
        return [row_text] if has_usable_text(row_text) else []

    return extract_text_blocks(tag)


def is_inline_text(element: PageElement) -> bool:
    if isinstance(element, NavigableString):
        return True

    if not isinstance(element, Tag):
        return False

    if element.name in TEXT_BLOCK_TAG_NAMES or element.name == "tr":
        return False

    return not has_structural_text_children(element)


def has_structural_text_children(tag: Tag) -> bool:
    return tag.find([*TEXT_BLOCK_TAG_NAMES, "tr"]) is not None


def add_inline_fragment(
    inline_fragments: list[str],
    element: PageElement,
) -> None:
    text = get_inline_text(element)

    if has_usable_text(text):
        inline_fragments.append(text)


def flush_inline_fragments(
    text_blocks: list[str],
    inline_fragments: list[str],
) -> None:
    if not inline_fragments:
        return

    text_blocks.append(INLINE_JOINER.join(inline_fragments))
    inline_fragments.clear()


def get_inline_text(element: PageElement) -> str:
    if isinstance(element, NavigableString):
        return normalize_inline_text(str(element))

    if isinstance(element, Tag):
        return normalize_inline_text(element.get_text(INLINE_JOINER, strip=True))

    return ""


def get_block_text(tag: Tag) -> str:
    if tag.name == "pre":
        return normalize_preformatted_text(tag.get_text(BLOCK_JOINER, strip=True))

    return normalize_inline_text(tag.get_text(INLINE_JOINER, strip=True))


def get_table_row_text(tag: Tag) -> str:
    cell_texts = [
        get_block_text(cell)
        for cell in tag.find_all(TABLE_CELL_TAG_NAMES, recursive=False)
    ]
    usable_cell_texts = [text for text in cell_texts if has_usable_text(text)]

    if usable_cell_texts:
        return TABLE_CELL_JOINER.join(usable_cell_texts)

    return get_block_text(tag)


def normalize_inline_text(text: str) -> str:
    return INLINE_JOINER.join(text.split())


def normalize_preformatted_text(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    usable_lines = [line for line in lines if has_usable_text(line)]
    return BLOCK_JOINER.join(usable_lines)


def has_usable_text(text: str) -> bool:
    return bool(text.strip())


def reject_epub_without_usable_text() -> NoReturn:
    logger.warning("Rejected EPUB source with no usable text.")
    raise EpubParseError("EPUB source did not contain usable text.")


def reject_malformed_epub(error: Exception) -> NoReturn:
    logger.warning("Rejected malformed EPUB source.")
    raise EpubParseError("EPUB source is malformed or unreadable.") from error


def reject_malformed_epub_spine() -> NoReturn:
    logger.warning("Rejected malformed EPUB source.")
    raise EpubParseError("EPUB source contains an invalid reading order.")
