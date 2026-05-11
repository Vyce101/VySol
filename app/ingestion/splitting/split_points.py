SPLIT_DELIMITERS = (
    "\n\n",
    "\n",
    ".",
    "!",
    "?",
    " ",
)


def find_next_split_index(
    text: str,
    chunk_size: int,
    max_lookback_size: int,
) -> int:
    if len(text) <= chunk_size:
        return len(text)

    search_start_index = max(0, chunk_size - max_lookback_size)

    for delimiter in SPLIT_DELIMITERS:
        delimiter_index = text.rfind(delimiter, search_start_index, chunk_size)
        if delimiter_index != -1:
            return delimiter_index + len(delimiter)

    return chunk_size
