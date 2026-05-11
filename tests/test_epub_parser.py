import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ebooklib import epub

from app.ingestion.parsing import EpubParseError, parse_epub_file

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00"
    b"\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)


class EpubParserTests(unittest.TestCase):
    def test_parses_text_epub_in_spine_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.epub"
            write_test_epub(
                source_file_path,
                [
                    make_document("chapter-1", "chapter-1.xhtml", "<p>First.</p>"),
                    make_document("chapter-2", "chapter-2.xhtml", "<p>Second.</p>"),
                ],
                ["chapter-2", "chapter-1"],
            )

            self.assertEqual(parse_epub_file(source_file_path), "Second.\n\nFirst.")

    def test_uses_spine_order_instead_of_manifest_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.epub"
            write_test_epub(
                source_file_path,
                [
                    make_document("manifest-first", "first.xhtml", "<p>One.</p>"),
                    make_document("manifest-second", "second.xhtml", "<p>Two.</p>"),
                    make_document("manifest-third", "third.xhtml", "<p>Three.</p>"),
                ],
                ["manifest-third", "manifest-first", "manifest-second"],
            )

            self.assertEqual(parse_epub_file(source_file_path), "Three.\n\nOne.\n\nTwo.")

    def test_preserves_meaningful_paragraph_and_line_structure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.epub"
            write_test_epub(
                source_file_path,
                [
                    make_document(
                        "chapter",
                        "chapter.xhtml",
                        """
                        <h1>Chapter One</h1>
                        <p>First <em>paragraph</em> line.</p>
                        <ul>
                            <li>First list item.</li>
                            <li>Second list item.</li>
                        </ul>
                        <blockquote>Quoted line.</blockquote>
                        """,
                    )
                ],
                ["chapter"],
            )

            self.assertEqual(
                parse_epub_file(source_file_path),
                "\n".join(
                    [
                        "Chapter One",
                        "First paragraph line.",
                        "First list item.",
                        "Second list item.",
                        "Quoted line.",
                    ]
                ),
            )

    def test_rejects_image_only_epub_and_logs_warning_without_text(self) -> None:
        parsed_text = "Do not log this source text."

        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.epub"
            write_test_epub(
                source_file_path,
                [
                    make_document(
                        "chapter",
                        "chapter.xhtml",
                        '<img src="images/picture.png" alt="">',
                    )
                ],
                ["chapter"],
                include_image=True,
            )

            with patch("app.ingestion.parsing.epub.logger") as logger:
                with self.assertRaises(EpubParseError):
                    parse_epub_file(source_file_path)

            logger.warning.assert_called_once()
            self.assertNotIn(parsed_text, str(logger.method_calls))

    def test_rejects_whitespace_only_epub(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.epub"
            write_test_epub(
                source_file_path,
                [make_document("chapter", "chapter.xhtml", "<p>   </p>")],
                ["chapter"],
            )

            with patch("app.ingestion.parsing.epub.logger") as logger:
                with self.assertRaises(EpubParseError):
                    parse_epub_file(source_file_path)

            logger.warning.assert_called_once()

    def test_epub_with_images_and_text_parses_text_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.epub"
            write_test_epub(
                source_file_path,
                [
                    make_document(
                        "chapter",
                        "chapter.xhtml",
                        '<p>Visible story text.</p><img src="images/picture.png" alt="">',
                    )
                ],
                ["chapter"],
                include_image=True,
            )

            self.assertEqual(parse_epub_file(source_file_path), "Visible story text.")

    def test_rejects_malformed_epub_and_logs_warning_without_text(self) -> None:
        parsed_text = "Do not log this source text."

        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.epub"
            source_file_path.write_bytes(b"not an epub")

            with patch("app.ingestion.parsing.epub.logger") as logger:
                with self.assertRaises(EpubParseError):
                    parse_epub_file(source_file_path)

            logger.warning.assert_called_once()
            self.assertNotIn(parsed_text, str(logger.method_calls))

    def test_success_logs_info_without_parsed_text(self) -> None:
        parsed_text = "Do not log this source text."

        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.epub"
            write_test_epub(
                source_file_path,
                [make_document("chapter", "chapter.xhtml", f"<p>{parsed_text}</p>")],
                ["chapter"],
            )

            with patch("app.ingestion.parsing.epub.logger") as logger:
                self.assertEqual(parse_epub_file(source_file_path), parsed_text)

            logger.info.assert_called_once()
            self.assertNotIn(parsed_text, str(logger.method_calls))


def make_document(uid: str, file_name: str, body: str) -> epub.EpubHtml:
    document = epub.EpubHtml(uid=uid, file_name=file_name, title=uid, lang="en")
    document.content = f"<html><body>{body}</body></html>"
    return document


def write_test_epub(
    source_file_path: Path,
    documents: list[epub.EpubHtml],
    spine_ids: list[str],
    *,
    include_image: bool = False,
) -> None:
    book = epub.EpubBook()
    book.set_identifier("test-epub")
    book.set_title("Test EPUB")
    book.set_language("en")

    for document in documents:
        book.add_item(document)

    if include_image:
        image = epub.EpubItem(
            uid="picture",
            file_name="images/picture.png",
            media_type="image/png",
            content=PNG_BYTES,
        )
        book.add_item(image)

    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine_ids
    epub.write_epub(str(source_file_path), book)


if __name__ == "__main__":
    unittest.main()
