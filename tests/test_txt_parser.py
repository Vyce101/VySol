import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ingestion.parsing import TxtParseError, parse_txt_file


class TxtParserTests(unittest.TestCase):
    def test_decodes_plain_utf8_to_exact_text(self) -> None:
        parsed_text = "First line\r\nSecond line.\nThird line."

        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.txt"
            source_file_path.write_bytes(parsed_text.encode("utf-8"))

            self.assertEqual(parse_txt_file(source_file_path), parsed_text)

    def test_decodes_utf8_bom_without_exposing_bom_character(self) -> None:
        parsed_text = "Opening text.\nMore text."

        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.txt"
            source_file_path.write_bytes(b"\xef\xbb\xbf" + parsed_text.encode("utf-8"))

            self.assertEqual(parse_txt_file(source_file_path), parsed_text)

    def test_decodes_utf16_bom_text(self) -> None:
        parsed_text = "Chapter one.\r\nChapter two."

        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.txt"
            source_file_path.write_bytes(parsed_text.encode("utf-16"))

            self.assertEqual(parse_txt_file(source_file_path), parsed_text)

    def test_decodes_utf32_bom_text(self) -> None:
        parsed_text = "Wide text.\nStill text."

        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.txt"
            source_file_path.write_bytes(parsed_text.encode("utf-32"))

            self.assertEqual(parse_txt_file(source_file_path), parsed_text)

    def test_rejects_unsupported_or_invalid_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.txt"
            source_file_path.write_bytes(b"\xff\xff\xff")

            with self.assertRaises(TxtParseError):
                parse_txt_file(source_file_path)

    def test_rejects_invalid_utf8_that_would_require_replacement(self) -> None:
        parsed_text = "Do not log this source text."

        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.txt"
            source_file_path.write_bytes(parsed_text.encode("utf-8") + b"\x80")

            with patch("app.ingestion.parsing.txt.logger") as logger:
                with self.assertRaises(TxtParseError):
                    parse_txt_file(source_file_path)

            logger.warning.assert_called_once()
            self.assertNotIn(parsed_text, str(logger.method_calls))

    def test_missing_current_file_logs_warning_without_raw_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "missing.txt"

            with patch("app.ingestion.parsing.txt.logger") as logger:
                with self.assertRaises(TxtParseError):
                    parse_txt_file(source_file_path)

            logger.warning.assert_called_once_with(
                "Rejected unavailable TXT source: error_type=%s",
                "FileNotFoundError",
            )
            logger.error.assert_not_called()
            self.assertNotIn(str(source_file_path), str(logger.method_calls))

    def test_unreadable_current_file_logs_warning_without_raw_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.txt"
            source_file_path.write_text("Source text.", encoding="utf-8")

            with (
                patch.object(Path, "open", side_effect=PermissionError("denied")),
                patch("app.ingestion.parsing.txt.logger") as logger,
            ):
                with self.assertRaises(TxtParseError):
                    parse_txt_file(source_file_path)

            logger.warning.assert_called_once_with(
                "Rejected unavailable TXT source: error_type=%s",
                "PermissionError",
            )
            logger.error.assert_not_called()
            self.assertNotIn(str(source_file_path), str(logger.method_calls))

    def test_success_logs_info_without_parsed_text(self) -> None:
        parsed_text = "Do not log this source text."

        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.txt"
            source_file_path.write_bytes(parsed_text.encode("utf-8"))

            with patch("app.ingestion.parsing.txt.logger") as logger:
                self.assertEqual(parse_txt_file(source_file_path), parsed_text)

            logger.info.assert_called_once()
            self.assertNotIn(parsed_text, str(logger.method_calls))


if __name__ == "__main__":
    unittest.main()
