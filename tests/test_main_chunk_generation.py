import unittest
from unittest.mock import patch

from app.draft_worlds.splitter_settings import SplitterSettings
from app.ingestion.splitting import (
    MainChunk,
    MainChunkGenerationError,
    generate_main_chunks,
)


class MainChunkGenerationTests(unittest.TestCase):
    def test_short_text_returns_one_exact_chunk(self) -> None:
        parsed_text = "Short text."

        chunks = generate_main_chunks(
            parsed_text,
            make_splitter_settings(chunk_size=100, max_lookback_size=20),
        )

        self.assertEqual(
            chunks,
            [
                MainChunk(
                    chunk_number=1,
                    chunk_text=parsed_text,
                    character_start_offset=0,
                    character_end_offset=len(parsed_text),
                )
            ],
        )

    def test_generates_ordered_chunks_using_preferred_split_points(self) -> None:
        parsed_text = "First paragraph.\n\nSecond sentence. Third sentence."

        chunks = generate_main_chunks(
            parsed_text,
            make_splitter_settings(
                chunk_size=len("First paragraph.\n\nSecond"),
                max_lookback_size=20,
            ),
        )

        self.assertEqual(
            chunks,
            [
                MainChunk(
                    chunk_number=1,
                    chunk_text="First paragraph.\n\n",
                    character_start_offset=0,
                    character_end_offset=18,
                ),
                MainChunk(
                    chunk_number=2,
                    chunk_text="Second sentence.",
                    character_start_offset=18,
                    character_end_offset=34,
                ),
                MainChunk(
                    chunk_number=3,
                    chunk_text=" Third sentence.",
                    character_start_offset=34,
                    character_end_offset=50,
                ),
            ],
        )
        self.assertEqual(join_chunk_text(chunks), parsed_text)
        self.assertEqual(chunk_offset_ranges(chunks), [(0, 18), (18, 34), (34, 50)])

    def test_hard_splits_when_no_delimiter_is_found(self) -> None:
        parsed_text = "abcdefghijklmnopqrstuvwxyz"

        chunks = generate_main_chunks(
            parsed_text,
            make_splitter_settings(chunk_size=10, max_lookback_size=5),
        )

        self.assertEqual(
            chunks,
            [
                MainChunk(
                    chunk_number=1,
                    chunk_text="abcdefghij",
                    character_start_offset=0,
                    character_end_offset=10,
                ),
                MainChunk(
                    chunk_number=2,
                    chunk_text="klmnopqrst",
                    character_start_offset=10,
                    character_end_offset=20,
                ),
                MainChunk(
                    chunk_number=3,
                    chunk_text="uvwxyz",
                    character_start_offset=20,
                    character_end_offset=26,
                ),
            ],
        )
        self.assertEqual(join_chunk_text(chunks), parsed_text)
        self.assertEqual(chunk_offset_ranges(chunks), [(0, 10), (10, 20), (20, 26)])

    def test_preserves_leading_and_trailing_whitespace(self) -> None:
        parsed_text = "  Leading words. Trailing words.  "

        chunks = generate_main_chunks(
            parsed_text,
            make_splitter_settings(chunk_size=18, max_lookback_size=10),
        )

        self.assertEqual(join_chunk_text(chunks), parsed_text)
        self.assertEqual(chunk_offset_ranges(chunks), [(0, 16), (16, 34)])
        self.assertTrue(chunks[0].chunk_text.startswith("  "))
        self.assertTrue(chunks[-1].chunk_text.endswith("  "))

    def test_preserves_whitespace_only_text(self) -> None:
        parsed_text = "\n\n   \n"

        chunks = generate_main_chunks(
            parsed_text,
            make_splitter_settings(chunk_size=2, max_lookback_size=1),
        )

        self.assertEqual(join_chunk_text(chunks), parsed_text)
        self.assertEqual(
            chunks,
            [
                MainChunk(
                    chunk_number=1,
                    chunk_text="\n\n",
                    character_start_offset=0,
                    character_end_offset=2,
                ),
                MainChunk(
                    chunk_number=2,
                    chunk_text="  ",
                    character_start_offset=2,
                    character_end_offset=4,
                ),
                MainChunk(
                    chunk_number=3,
                    chunk_text=" \n",
                    character_start_offset=4,
                    character_end_offset=6,
                ),
            ],
        )

    def test_empty_parsed_text_returns_empty_list(self) -> None:
        chunks = generate_main_chunks(
            "",
            make_splitter_settings(chunk_size=10, max_lookback_size=5),
        )

        self.assertEqual(chunks, [])

    def test_chunk_numbers_start_at_one_and_increment_in_order(self) -> None:
        chunks = generate_main_chunks(
            "one two three four five",
            make_splitter_settings(chunk_size=8, max_lookback_size=4),
        )

        self.assertEqual([chunk.chunk_number for chunk in chunks], [1, 2, 3, 4])

    def test_logs_and_raises_when_splitter_raises_unexpectedly(self) -> None:
        parsed_text = "Do not log this source text."

        with (
            patch(
                "app.ingestion.splitting.main_chunks.find_next_split_index",
                side_effect=RuntimeError("splitter failed"),
            ),
            patch("app.ingestion.splitting.main_chunks.logger") as logger,
        ):
            with self.assertRaises(MainChunkGenerationError):
                generate_main_chunks(
                    parsed_text,
                    make_splitter_settings(chunk_size=10, max_lookback_size=5),
                )

        log_output = str(logger.method_calls)
        logger.error.assert_called_once()
        self.assertNotIn(parsed_text, log_output)

    def test_logs_and_raises_when_splitter_returns_non_progressing_index(self) -> None:
        parsed_text = "Do not log this source text."

        with (
            patch(
                "app.ingestion.splitting.main_chunks.find_next_split_index",
                return_value=0,
            ),
            patch("app.ingestion.splitting.main_chunks.logger") as logger,
        ):
            with self.assertRaises(MainChunkGenerationError):
                generate_main_chunks(
                    parsed_text,
                    make_splitter_settings(chunk_size=10, max_lookback_size=5),
                )

        log_output = str(logger.method_calls)
        logger.error.assert_called_once()
        self.assertNotIn(parsed_text, log_output)

    def test_logs_and_raises_when_splitter_returns_out_of_range_index(self) -> None:
        parsed_text = "Do not log this source text."

        with (
            patch(
                "app.ingestion.splitting.main_chunks.find_next_split_index",
                return_value=len(parsed_text) + 1,
            ),
            patch("app.ingestion.splitting.main_chunks.logger") as logger,
        ):
            with self.assertRaises(MainChunkGenerationError):
                generate_main_chunks(
                    parsed_text,
                    make_splitter_settings(chunk_size=10, max_lookback_size=5),
                )

        log_output = str(logger.method_calls)
        logger.error.assert_called_once()
        self.assertNotIn(parsed_text, log_output)


def make_splitter_settings(
    *,
    chunk_size: int,
    max_lookback_size: int,
) -> SplitterSettings:
    return SplitterSettings(
        chunk_size=chunk_size,
        max_lookback_size=max_lookback_size,
        overlap_size=0,
        splitter_version="test",
    )


def join_chunk_text(chunks: list[MainChunk]) -> str:
    return "".join(chunk.chunk_text for chunk in chunks)


def chunk_offset_ranges(chunks: list[MainChunk]) -> list[tuple[int, int]]:
    return [
        (chunk.character_start_offset, chunk.character_end_offset)
        for chunk in chunks
    ]


if __name__ == "__main__":
    unittest.main()
