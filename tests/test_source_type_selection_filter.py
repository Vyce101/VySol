import unittest
from pathlib import Path
from unittest.mock import patch

from app.ingestion.staging.source_type_filter import (
    SourceStagingItem,
    UNSUPPORTED_SOURCE_TYPE_MESSAGE,
    build_source_staging_list,
    can_start_ingestion,
)


class SourceTypeSelectionFilterTests(unittest.TestCase):
    def test_accepts_supported_source_types(self) -> None:
        staged_sources = build_source_staging_list(
            [
                Path("notes.txt"),
                Path("book.epub"),
                Path("manual.pdf"),
            ]
        )

        self.assertEqual(
            staged_sources,
            [
                SourceStagingItem(Path("notes.txt"), "txt", True, None),
                SourceStagingItem(Path("book.epub"), "epub", True, None),
                SourceStagingItem(Path("manual.pdf"), "pdf", True, None),
            ],
        )

    def test_accepts_mixed_case_extensions(self) -> None:
        staged_sources = build_source_staging_list([Path("manual.PDF")])

        self.assertEqual(
            staged_sources,
            [SourceStagingItem(Path("manual.PDF"), "pdf", True, None)],
        )

    def test_keeps_unsupported_extension_as_invalid_staged_source(self) -> None:
        staged_sources = build_source_staging_list([Path("outline.docx")])

        self.assertEqual(
            staged_sources,
            [
                SourceStagingItem(
                    Path("outline.docx"),
                    "docx",
                    False,
                    UNSUPPORTED_SOURCE_TYPE_MESSAGE,
                )
            ],
        )

    def test_keeps_missing_extension_as_invalid_staged_source(self) -> None:
        staged_sources = build_source_staging_list([Path("outline")])

        self.assertEqual(
            staged_sources,
            [
                SourceStagingItem(
                    Path("outline"),
                    "missing",
                    False,
                    UNSUPPORTED_SOURCE_TYPE_MESSAGE,
                )
            ],
        )

    def test_preserves_mixed_source_selection_order(self) -> None:
        source_file_paths = [
            Path("one.txt"),
            Path("two.docx"),
            Path("three.epub"),
            Path("four"),
            Path("five.pdf"),
        ]

        staged_sources = build_source_staging_list(source_file_paths)

        self.assertEqual(
            [source.source_file_path for source in staged_sources],
            source_file_paths,
        )
        self.assertEqual(
            [source.is_valid for source in staged_sources],
            [True, False, True, False, True],
        )

    def test_can_start_ingestion_when_all_staged_sources_are_valid(self) -> None:
        staged_sources = build_source_staging_list(
            [
                Path("notes.txt"),
                Path("book.epub"),
            ]
        )

        self.assertTrue(can_start_ingestion(staged_sources))

    def test_cannot_start_ingestion_when_any_staged_source_is_invalid(self) -> None:
        staged_sources = build_source_staging_list(
            [
                Path("notes.txt"),
                Path("outline.docx"),
            ]
        )

        self.assertFalse(can_start_ingestion(staged_sources))

    def test_cannot_start_ingestion_with_empty_staging_list(self) -> None:
        self.assertFalse(can_start_ingestion([]))

    def test_logs_unsupported_source_type_without_full_path(self) -> None:
        source_path = Path("private") / "source.docx"

        with patch("app.ingestion.staging.source_type_filter.logger") as logger:
            build_source_staging_list([source_path])

        logger.warning.assert_called_once_with(
            "Unsupported staged source type selected: source_type=%s",
            "docx",
        )
        self.assertNotIn(str(source_path), str(logger.method_calls))

    def test_logs_missing_source_type_without_full_path(self) -> None:
        source_path = Path("private") / "source"

        with patch("app.ingestion.staging.source_type_filter.logger") as logger:
            build_source_staging_list([source_path])

        logger.warning.assert_called_once_with(
            "Unsupported staged source type selected: source_type=%s",
            "missing",
        )
        self.assertNotIn(str(source_path), str(logger.method_calls))

    def test_unexpected_filter_failure_logs_error(self) -> None:
        with (
            patch(
                "app.ingestion.staging.source_type_filter.build_source_staging_item",
                side_effect=ValueError("filter failed"),
            ),
            patch("app.ingestion.staging.source_type_filter.logger") as logger,
        ):
            with self.assertRaises(RuntimeError):
                build_source_staging_list([Path("source.txt")])

        logger.error.assert_called_once_with(
            "Unexpected source type filter failure.",
            exc_info=True,
        )


if __name__ == "__main__":
    unittest.main()
