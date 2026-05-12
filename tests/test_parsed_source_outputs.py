import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from app.ingestion.attempt_workspace import TemporaryIngestionWorkspace
from app.ingestion.parsed_source_outputs import (
    ParsedSourcePreparationError,
    TemporaryParsedSourceOutput,
    UnusableParsedSourceTextError,
    prepare_parsed_source_outputs,
)
from app.ingestion.parsing.router import (
    ParsedStagedSource,
    StagedSource,
    UnsupportedSourceTypeError,
)
from app.ingestion.parsing.txt import TxtParseError
from app.ingestion.staging.source_staging_state import TemporarySourceStagingEntry


class ParsedSourceOutputPreparationTests(unittest.TestCase):
    def test_prepares_parsed_outputs_in_order(self) -> None:
        entries = (
            make_entry("entry-1", Path("first.txt"), "TXT"),
            make_entry("entry-2", Path("second.pdf"), "pdf"),
        )
        parsed_sources = (
            ParsedStagedSource(Path("first.txt"), "txt", "First text."),
            ParsedStagedSource(Path("second.pdf"), "pdf", "Second text."),
        )

        with patch(
            "app.ingestion.parsed_source_outputs.parse_staged_source",
            side_effect=parsed_sources,
        ) as parse_staged_source:
            outputs = prepare_parsed_source_outputs(make_workspace(), entries)

        self.assertEqual(
            outputs,
            (
                TemporaryParsedSourceOutput(
                    attempt_id="attempt-1",
                    staging_entry_id="entry-1",
                    source_file_type="txt",
                    parsed_text="First text.",
                ),
                TemporaryParsedSourceOutput(
                    attempt_id="attempt-1",
                    staging_entry_id="entry-2",
                    source_file_type="pdf",
                    parsed_text="Second text.",
                ),
            ),
        )
        self.assertEqual(
            parse_staged_source.call_args_list,
            [
                call(make_staged_source_call(Path("first.txt"), "TXT")),
                call(make_staged_source_call(Path("second.pdf"), "pdf")),
            ],
        )

    def test_stops_parsing_after_first_parser_failure(self) -> None:
        entries = (
            make_entry("entry-1", Path("first.txt"), "txt"),
            make_entry("entry-2", Path("second.txt"), "txt"),
        )
        parse_error = TxtParseError("TXT source could not be decoded.")

        with patch(
            "app.ingestion.parsed_source_outputs.parse_staged_source",
            side_effect=parse_error,
        ) as parse_staged_source:
            with self.assertRaises(TxtParseError):
                prepare_parsed_source_outputs(make_workspace(), entries)

        parse_staged_source.assert_called_once_with(
            make_staged_source_call(Path("first.txt"), "txt")
        )

    def test_parser_rejection_logs_warning_without_text_or_path(self) -> None:
        source_path = Path("private") / "source.txt"
        parsed_text = "Do not log this source text."
        entry = make_entry("entry-1", source_path, "txt")

        with (
            patch(
                "app.ingestion.parsed_source_outputs.parse_staged_source",
                side_effect=TxtParseError(parsed_text),
            ),
            patch("app.ingestion.parsed_source_outputs.logger") as logger,
        ):
            with self.assertRaises(TxtParseError):
                prepare_parsed_source_outputs(make_workspace(), (entry,))

        logger.warning.assert_called_once_with(
            "Rejected staged source during parse preparation: "
            "attempt_id=%s staging_entry_id=%s source_type=%s",
            "attempt-1",
            "entry-1",
            "txt",
        )
        logger.error.assert_not_called()
        self.assertNotIn(parsed_text, str(logger.method_calls))
        self.assertNotIn(str(source_path), str(logger.method_calls))

    def test_unsupported_type_rejection_logs_warning(self) -> None:
        entry = make_entry("entry-1", Path("source.docx"), "docx")

        with (
            patch(
                "app.ingestion.parsed_source_outputs.parse_staged_source",
                side_effect=UnsupportedSourceTypeError("unsupported"),
            ),
            patch("app.ingestion.parsed_source_outputs.logger") as logger,
        ):
            with self.assertRaises(UnsupportedSourceTypeError):
                prepare_parsed_source_outputs(make_workspace(), (entry,))

        logger.warning.assert_called_once()
        logger.error.assert_not_called()

    def test_unusable_text_rejection_blocks_batch_and_does_not_parse_next_source(
        self,
    ) -> None:
        entries = (
            make_entry("entry-1", Path("first.txt"), "txt"),
            make_entry("entry-2", Path("second.txt"), "txt"),
        )

        with (
            patch(
                "app.ingestion.parsed_source_outputs.parse_staged_source",
                return_value=ParsedStagedSource(Path("first.txt"), "txt", "   \n"),
            ) as parse_staged_source,
            patch("app.ingestion.parsed_source_outputs.logger") as logger,
        ):
            with self.assertRaises(UnusableParsedSourceTextError):
                prepare_parsed_source_outputs(make_workspace(), entries)

        parse_staged_source.assert_called_once_with(
            make_staged_source_call(Path("first.txt"), "txt")
        )
        logger.warning.assert_called_once_with(
            "Rejected staged source with no usable parsed text: "
            "attempt_id=%s staging_entry_id=%s source_type=%s",
            "attempt-1",
            "entry-1",
            "txt",
        )

    def test_unexpected_failure_logs_error_without_text_or_path(self) -> None:
        source_path = Path("private") / "source.txt"
        parsed_text = "Do not log this source text."
        entry = make_entry("entry-1", source_path, "txt")

        with (
            patch(
                "app.ingestion.parsed_source_outputs.parse_staged_source",
                side_effect=RuntimeError(parsed_text),
            ),
            patch("app.ingestion.parsed_source_outputs.logger") as logger,
        ):
            with self.assertRaises(ParsedSourcePreparationError):
                prepare_parsed_source_outputs(make_workspace(), (entry,))

        logger.error.assert_called_once_with(
            "Unexpected parsed source preparation failure: "
            "attempt_id=%s staging_entry_id=%s source_type=%s error_type=%s",
            "attempt-1",
            "entry-1",
            "txt",
            "RuntimeError",
        )
        logger.warning.assert_not_called()
        self.assertNotIn(parsed_text, str(logger.method_calls))
        self.assertNotIn(str(source_path), str(logger.method_calls))

    def test_success_logs_info_without_parsed_text(self) -> None:
        parsed_text = "Do not log this source text."
        entry = make_entry("entry-1", Path("source.txt"), "txt")

        with (
            patch(
                "app.ingestion.parsed_source_outputs.parse_staged_source",
                return_value=ParsedStagedSource(Path("source.txt"), "txt", parsed_text),
            ),
            patch("app.ingestion.parsed_source_outputs.logger") as logger,
        ):
            prepare_parsed_source_outputs(make_workspace(), (entry,))

        logger.info.assert_called_once_with(
            "Prepared parsed source output: "
            "attempt_id=%s staging_entry_id=%s source_type=%s character_count=%s",
            "attempt-1",
            "entry-1",
            "txt",
            len(parsed_text),
        )
        self.assertNotIn(parsed_text, str(logger.method_calls))

    def test_outputs_do_not_include_committed_identity_or_book_numbers(self) -> None:
        entry = make_entry("entry-1", Path("source.txt"), "txt")

        with patch(
            "app.ingestion.parsed_source_outputs.parse_staged_source",
            return_value=ParsedStagedSource(Path("source.txt"), "txt", "Source text."),
        ):
            outputs = prepare_parsed_source_outputs(make_workspace(), (entry,))

        output_fields = set(outputs[0].__dataclass_fields__)
        self.assertEqual(
            output_fields,
            {"attempt_id", "staging_entry_id", "source_file_type", "parsed_text"},
        )
        self.assertNotIn("book_number", output_fields)
        self.assertNotIn("source_id", output_fields)
        self.assertNotIn("stored_path", output_fields)

    def test_does_not_write_parsed_text_to_temporary_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            workspace = TemporaryIngestionWorkspace("attempt-1", Path(temp_directory))
            entry = make_entry("entry-1", Path("source.txt"), "txt")

            with patch(
                "app.ingestion.parsed_source_outputs.parse_staged_source",
                return_value=ParsedStagedSource(
                    Path("source.txt"),
                    "txt",
                    "Source text.",
                ),
            ):
                prepare_parsed_source_outputs(workspace, (entry,))

            self.assertEqual(list(Path(temp_directory).iterdir()), [])


def make_workspace() -> TemporaryIngestionWorkspace:
    return TemporaryIngestionWorkspace(
        attempt_id="attempt-1",
        workspace_path=Path("temporary-workspace"),
    )


def make_entry(
    staging_entry_id: str,
    source_file_path: Path,
    source_file_type: str,
) -> TemporarySourceStagingEntry:
    return TemporarySourceStagingEntry(
        staging_entry_id=staging_entry_id,
        source_file_path=source_file_path,
        source_file_type=source_file_type,
        is_valid=True,
        error_message=None,
    )


def make_staged_source_call(source_file_path: Path, source_file_type: str):
    return StagedSource(
        source_file_path=source_file_path,
        source_file_type=source_file_type,
    )


if __name__ == "__main__":
    unittest.main()
