import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.ingestion.parsing.router import (
    ParsedStagedSource,
    StagedSource,
    UnsupportedSourceTypeError,
    parse_staged_source,
    parse_staged_source_batch,
)
from app.ingestion.parsing.txt import TxtParseError


class SourceParserRouterTests(unittest.TestCase):
    def test_routes_txt_source_to_txt_parser(self) -> None:
        source = StagedSource(Path("source.txt"), "txt")

        with patch_parser_map({"txt": "text"}) as parsers:
            parsed_source = parse_staged_source(source)

        parsers["txt"].assert_called_once_with(source.source_file_path)
        parsers["epub"].assert_not_called()
        parsers["pdf"].assert_not_called()
        self.assertEqual(
            parsed_source,
            ParsedStagedSource(source.source_file_path, "txt", "text"),
        )

    def test_routes_epub_source_to_epub_parser(self) -> None:
        source = StagedSource(Path("source.epub"), "epub")

        with patch_parser_map({"epub": "book text"}) as parsers:
            parsed_source = parse_staged_source(source)

        parsers["epub"].assert_called_once_with(source.source_file_path)
        parsers["txt"].assert_not_called()
        parsers["pdf"].assert_not_called()
        self.assertEqual(parsed_source.source_file_type, "epub")
        self.assertEqual(parsed_source.parsed_text, "book text")

    def test_routes_pdf_source_to_pdf_parser(self) -> None:
        source = StagedSource(Path("source.pdf"), "pdf")

        with patch_parser_map({"pdf": "pdf text"}) as parsers:
            parsed_source = parse_staged_source(source)

        parsers["pdf"].assert_called_once_with(source.source_file_path)
        parsers["txt"].assert_not_called()
        parsers["epub"].assert_not_called()
        self.assertEqual(parsed_source.source_file_type, "pdf")
        self.assertEqual(parsed_source.parsed_text, "pdf text")

    def test_normalizes_mixed_case_source_type(self) -> None:
        source = StagedSource(Path("source.txt"), " TxT ")

        with patch_parser_map({"txt": "text"}) as parsers:
            parsed_source = parse_staged_source(source)

        parsers["txt"].assert_called_once_with(source.source_file_path)
        self.assertEqual(parsed_source.source_file_type, "txt")

    def test_rejects_unsupported_source_type(self) -> None:
        source = StagedSource(Path("source.docx"), "docx")

        with (
            patch_parser_map({}) as parsers,
            patch("app.ingestion.parsing.router.logger") as logger,
        ):
            with self.assertRaises(UnsupportedSourceTypeError):
                parse_staged_source(source)

        logger.warning.assert_called_once()
        parsers["txt"].assert_not_called()
        parsers["epub"].assert_not_called()
        parsers["pdf"].assert_not_called()

    def test_rejects_blank_source_type(self) -> None:
        source = StagedSource(Path("source.txt"), "  ")

        with patch("app.ingestion.parsing.router.logger") as logger:
            with self.assertRaises(UnsupportedSourceTypeError):
                parse_staged_source(source)

        logger.warning.assert_called_once()

    def test_batch_rejects_unsupported_type_before_calling_any_parser(self) -> None:
        sources = [
            StagedSource(Path("source.txt"), "txt"),
            StagedSource(Path("source.docx"), "docx"),
        ]

        with patch_parser_map({"txt": "text"}) as parsers:
            with self.assertRaises(UnsupportedSourceTypeError):
                parse_staged_source_batch(sources)

        parsers["txt"].assert_not_called()
        parsers["epub"].assert_not_called()
        parsers["pdf"].assert_not_called()

    def test_parser_failures_propagate_before_commit_work_can_continue(self) -> None:
        source = StagedSource(Path("fake.txt"), "txt")
        parse_error = TxtParseError("TXT source could not be decoded.")

        with patch_parser_map({"txt": parse_error}):
            with self.assertRaises(TxtParseError):
                parse_staged_source(source)

    def test_real_txt_parser_reads_current_edited_contents_at_parse_time(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.txt"
            source_file_path.write_text("Original text.", encoding="utf-8")
            source = StagedSource(source_file_path, "txt")
            source_file_path.write_text("Current edited text.", encoding="utf-8")

            parsed_source = parse_staged_source(source)

        self.assertEqual(parsed_source.parsed_text, "Current edited text.")

    def test_real_batch_parser_reads_current_contents_and_preserves_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            first_path = Path(temp_directory) / "first.txt"
            second_path = Path(temp_directory) / "second.txt"
            first_path.write_text("Original first.", encoding="utf-8")
            second_path.write_text("Original second.", encoding="utf-8")
            sources = [
                StagedSource(first_path, "txt"),
                StagedSource(second_path, "txt"),
            ]
            first_path.write_text("Current first.", encoding="utf-8")
            second_path.write_text("Current second.", encoding="utf-8")

            parsed_sources = parse_staged_source_batch(sources)

        self.assertEqual(
            parsed_sources,
            [
                ParsedStagedSource(first_path, "txt", "Current first."),
                ParsedStagedSource(second_path, "txt", "Current second."),
            ],
        )

    def test_missing_current_txt_file_fails_with_path_safe_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "missing.txt"
            source = StagedSource(source_file_path, "txt")

            with patch("app.ingestion.parsing.txt.logger") as logger:
                with self.assertRaises(TxtParseError):
                    parse_staged_source(source)

        logger.warning.assert_called_once_with(
            "Rejected unavailable TXT source: error_type=%s",
            "FileNotFoundError",
        )
        logger.error.assert_not_called()
        self.assertNotIn(str(source_file_path), str(logger.method_calls))

    def test_unreadable_current_txt_file_fails_with_path_safe_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "source.txt"
            source_file_path.write_text("Source text.", encoding="utf-8")
            source = StagedSource(source_file_path, "txt")

            with (
                patch.object(Path, "open", side_effect=PermissionError("denied")),
                patch("app.ingestion.parsing.txt.logger") as logger,
            ):
                with self.assertRaises(TxtParseError):
                    parse_staged_source(source)

        logger.warning.assert_called_once_with(
            "Rejected unavailable TXT source: error_type=%s",
            "PermissionError",
        )
        logger.error.assert_not_called()
        self.assertNotIn(str(source_file_path), str(logger.method_calls))

    def test_logs_routing_debug_without_source_text(self) -> None:
        source_text = "Do not log this source text."
        source = StagedSource(Path("source.txt"), "txt")

        with (
            patch_parser_map({"txt": source_text}),
            patch("app.ingestion.parsing.router.logger") as logger,
        ):
            parse_staged_source(source)

        logger.debug.assert_called_once()
        self.assertNotIn(source_text, str(logger.method_calls))

    def test_unexpected_router_failure_logs_error_without_source_text(self) -> None:
        source_text = "Do not log this source text."
        source = StagedSource(Path("source.txt"), "txt")

        with (
            patch_parser_map({"txt": RuntimeError(source_text)}),
            patch("app.ingestion.parsing.router.logger") as logger,
        ):
            with self.assertRaises(RuntimeError):
                parse_staged_source(source)

        logger.error.assert_called_once()
        self.assertNotIn(source_text, str(logger.method_calls))

    def test_real_txt_parser_rejects_fake_extension_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            source_file_path = Path(temp_directory) / "fake.txt"
            source_file_path.write_bytes(b"\xff\xff\xff")
            source = StagedSource(source_file_path, "txt")

            with self.assertRaises(TxtParseError):
                parse_staged_source(source)


def patch_parser_map(results_by_source_type: dict[str, object]):
    parsers = {
        "txt": make_parser(results_by_source_type.get("txt", "")),
        "epub": make_parser(results_by_source_type.get("epub", "")),
        "pdf": make_parser(results_by_source_type.get("pdf", "")),
    }
    return patch("app.ingestion.parsing.router.PARSERS_BY_SOURCE_TYPE", parsers)


def make_parser(result: object) -> Mock:
    if isinstance(result, Exception):
        return Mock(side_effect=result)

    return Mock(return_value=result)


if __name__ == "__main__":
    unittest.main()
