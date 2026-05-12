import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

from app.ingestion.parsing import PdfParseError, parse_pdf_file

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00"
    b"\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)


class PdfParserTests(unittest.TestCase):
    def test_parses_text_pdf_in_page_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.pdf"
            write_test_pdf(source_file_path, ["First page.", "Second page."])

            self.assertEqual(parse_pdf_file(source_file_path), "First page.\n\nSecond page.")

    def test_pdf_with_images_and_text_parses_text_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.pdf"
            write_test_pdf(source_file_path, ["Visible story text."], include_image=True)

            self.assertEqual(parse_pdf_file(source_file_path), "Visible story text.")

    def test_rejects_image_only_pdf_and_logs_warning_without_text(self) -> None:
        parsed_text = "Do not log this source text."

        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.pdf"
            write_test_pdf(source_file_path, [""], include_image=True)

            with patch("app.ingestion.parsing.pdf.logger") as logger:
                with self.assertRaises(PdfParseError):
                    parse_pdf_file(source_file_path)

            logger.warning.assert_called_once()
            self.assertNotIn(parsed_text, str(logger.method_calls))

    def test_rejects_whitespace_only_extracted_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.pdf"
            write_test_pdf(source_file_path, ["Visible source text."])

            with (
                patch("app.ingestion.parsing.pdf.extract_page_texts", return_value=["   \n"]),
                patch("app.ingestion.parsing.pdf.logger") as logger,
            ):
                with self.assertRaises(PdfParseError):
                    parse_pdf_file(source_file_path)

            logger.warning.assert_called_once()

    def test_rejects_broken_pdf_and_logs_error_without_text(self) -> None:
        parsed_text = "Do not log this source text."

        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.pdf"
            source_file_path.write_bytes(b"not a pdf")

            with patch("app.ingestion.parsing.pdf.logger") as logger:
                with self.assertRaises(PdfParseError):
                    parse_pdf_file(source_file_path)

            logger.error.assert_called_once()
            self.assertNotIn(parsed_text, str(logger.method_calls))

    def test_missing_current_file_logs_warning_without_raw_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "missing.pdf"

            with patch("app.ingestion.parsing.pdf.logger") as logger:
                with self.assertRaises(PdfParseError):
                    parse_pdf_file(source_file_path)

            logger.warning.assert_called_once_with(
                "Rejected unavailable PDF source: reason=%s",
                "missing",
            )
            logger.error.assert_not_called()
            self.assertNotIn(str(source_file_path), str(logger.method_calls))

    def test_directory_current_path_logs_warning_without_raw_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.pdf"
            source_file_path.mkdir()

            with patch("app.ingestion.parsing.pdf.logger") as logger:
                with self.assertRaises(PdfParseError):
                    parse_pdf_file(source_file_path)

            logger.warning.assert_called_once_with(
                "Rejected unavailable PDF source: reason=%s",
                "not_file",
            )
            logger.error.assert_not_called()
            self.assertNotIn(str(source_file_path), str(logger.method_calls))

    def test_unexpected_text_extraction_failure_logs_error_without_text(self) -> None:
        parsed_text = "Do not log this source text."

        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.pdf"
            write_test_pdf(source_file_path, [parsed_text])

            with (
                patch(
                    "app.ingestion.parsing.pdf.extract_page_text",
                    side_effect=RuntimeError("text extraction failed"),
                ),
                patch("app.ingestion.parsing.pdf.logger") as logger,
            ):
                with self.assertRaises(PdfParseError):
                    parse_pdf_file(source_file_path)

            logger.error.assert_called_once()
            self.assertNotIn(parsed_text, str(logger.method_calls))

    def test_success_logs_info_without_parsed_text(self) -> None:
        parsed_text = "Do not log this source text."

        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.pdf"
            write_test_pdf(source_file_path, [parsed_text])

            with patch("app.ingestion.parsing.pdf.logger") as logger:
                self.assertEqual(parse_pdf_file(source_file_path), parsed_text)

            logger.info.assert_called_once()
            self.assertNotIn(parsed_text, str(logger.method_calls))


def write_test_pdf(
    source_file_path: Path,
    page_texts: list[str],
    *,
    include_image: bool = False,
) -> None:
    document = pymupdf.open()

    try:
        for page_text in page_texts:
            page = document.new_page()

            if page_text:
                page.insert_text((72, 72), page_text, fontsize=12)

            if include_image:
                page.insert_image(
                    pymupdf.Rect(72, 96, 96, 120),
                    stream=PNG_BYTES,
                )

        document.save(source_file_path)
    finally:
        document.close()


if __name__ == "__main__":
    unittest.main()
