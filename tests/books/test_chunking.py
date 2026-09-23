import pytest

from vysol.books.chunking import split_text


@pytest.mark.parametrize("text,size,search", [
    ("First paragraph.\r\n\r\nSecond paragraph.\r\nLast.", 24, 10),
    ("x" * 57, 8, 3), ("世界🌕 café\n" * 20, 13, 5),
    (" \t\r\n" * 20, 5, 4), ("short", 8000, 1000), ("", 1, 0),
    ("世界🌕? Yes! Café...\r\nNext. " * 10, 18, 10),
])
def test_slices_reconstruct_source_with_codepoint_offsets(text, size, search):
    chunks = split_text(text, size, search)
    assert "".join(c.text for c in chunks) == text
    cursor = 0
    for chunk in chunks:
        assert chunk.start == cursor
        assert chunk.text == text[chunk.start:chunk.end]
        assert 0 < len(chunk.text) <= size
        cursor = chunk.end
    assert cursor == len(text)


def test_paragraph_priority_and_bounded_search():
    text = "aaaa\n\nbbbb ccc ddddd"
    assert split_text(text, 14, 10)[0].text == "aaaa\n\n"
    assert split_text(text, 14, 4)[0].text == "aaaa\n\nbbbb "
    assert split_text(text, 14, 0)[0].text == text[:14]


def test_crlf_is_one_line_break_and_paragraphs_take_priority():
    text = "aa\r\n\r\nbbbb\r\ncccc ddddd"
    assert split_text(text, 18, 15)[0].text == "aa\r\n\r\n"
    assert split_text("aa\r\nbbbb cccc ddddd", 16, 15)[0].text == "aa\r\n"


@pytest.mark.parametrize("punctuation", ["?", "!", ".", "?!", "..."])
def test_sentence_punctuation_precedes_spaces_and_stays_with_preceding_text(punctuation):
    text = f"aaaa{punctuation} bbbb cccc ddddd"
    chunks = split_text(text, 14, 10)
    assert chunks[0].text == f"aaaa{punctuation}"
    assert "".join(chunk.text for chunk in chunks) == text


@pytest.mark.parametrize("separator", ["\n\n", "\r\n\r\n", "\n", "\r\n"])
def test_paragraph_and_line_breaks_precede_sentence_punctuation(separator):
    text = f"aa{separator}bb? cc! dd.ee ff trailing"
    assert split_text(text, 18, 17)[0].text == f"aa{separator}"


def test_latest_sentence_boundary_and_search_window():
    assert split_text("aa? bb! cc. dd ee", 14, 12)[0].text == "aa? bb! cc."
    text = "aa. bbbb cccc dddd"
    assert split_text(text, 14, 5)[0].text == "aa. bbbb cccc "


@pytest.mark.parametrize("size,search", [(0, 0), (3, 3), (3, -1)])
def test_invalid_configuration(size, search):
    with pytest.raises(ValueError):
        split_text("abc", size, search)
