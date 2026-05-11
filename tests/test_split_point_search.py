import unittest

from app.ingestion.splitting import find_next_split_index


class SplitPointSearchTests(unittest.TestCase):
    def test_short_text_returns_text_length(self) -> None:
        text = "Short text."

        split_index = find_next_split_index(
            text,
            chunk_size=100,
            max_lookback_size=20,
        )

        self.assertEqual(split_index, len(text))

    def test_text_equal_to_chunk_size_returns_text_length(self) -> None:
        text = "Exact size"

        split_index = find_next_split_index(
            text,
            chunk_size=len(text),
            max_lookback_size=4,
        )

        self.assertEqual(split_index, len(text))

    def test_double_newline_wins_over_later_lower_priority_delimiters(self) -> None:
        text = "First paragraph.\n\nSecond line has spaces."

        split_index = find_next_split_index(
            text,
            chunk_size=len("First paragraph.\n\nSecond line has"),
            max_lookback_size=20,
        )

        self.assertEqual(text[:split_index], "First paragraph.\n\n")

    def test_single_newline_wins_when_double_newline_is_missing(self) -> None:
        text = "First line.\nSecond sentence. More words."

        split_index = find_next_split_index(
            text,
            chunk_size=len("First line.\nSecond sentence"),
            max_lookback_size=20,
        )

        self.assertEqual(text[:split_index], "First line.\n")

    def test_sentence_punctuation_wins_over_spaces(self) -> None:
        text = "First sentence. Second phrase has spaces"

        split_index = find_next_split_index(
            text,
            chunk_size=len("First sentence. Second phrase"),
            max_lookback_size=20,
        )

        self.assertEqual(text[:split_index], "First sentence.")

    def test_exclamation_mark_can_be_selected(self) -> None:
        text = "Alarm! Continue with more words"

        split_index = find_next_split_index(
            text,
            chunk_size=len("Alarm! Continue with"),
            max_lookback_size=20,
        )

        self.assertEqual(text[:split_index], "Alarm!")

    def test_question_mark_can_be_selected(self) -> None:
        text = "Question? Continue with more words"

        split_index = find_next_split_index(
            text,
            chunk_size=len("Question? Continue with"),
            max_lookback_size=20,
        )

        self.assertEqual(text[:split_index], "Question?")

    def test_last_space_is_used_when_no_higher_priority_delimiter_exists(self) -> None:
        text = "alpha beta gamma delta"

        split_index = find_next_split_index(
            text,
            chunk_size=len("alpha beta gamma"),
            max_lookback_size=10,
        )

        self.assertEqual(text[:split_index], "alpha beta ")

    def test_hard_splits_at_chunk_size_when_no_delimiter_is_found(self) -> None:
        text = "abcdefghijklmnopqrstuvwxyz"

        split_index = find_next_split_index(
            text,
            chunk_size=10,
            max_lookback_size=5,
        )

        self.assertEqual(split_index, 10)
        self.assertEqual(text[:split_index], "abcdefghij")

    def test_ignores_delimiters_before_lookback_window(self) -> None:
        text = "alpha beta-gammadelta"

        split_index = find_next_split_index(
            text,
            chunk_size=len("alpha beta-gamma"),
            max_lookback_size=5,
        )

        self.assertEqual(split_index, len("alpha beta-gamma"))

    def test_uses_latest_match_within_same_priority(self) -> None:
        text = "One. Two. Three keeps going"

        split_index = find_next_split_index(
            text,
            chunk_size=len("One. Two. Three"),
            max_lookback_size=20,
        )

        self.assertEqual(text[:split_index], "One. Two.")


if __name__ == "__main__":
    unittest.main()
