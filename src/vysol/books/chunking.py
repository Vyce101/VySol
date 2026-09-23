"""Lossless text slices with bounded, recursively preferred boundaries."""

from dataclasses import dataclass
import re

CHUNKER_VERSION = 2
BOUNDARIES = (re.compile(r"(?>\r\n|\r|\n)[ \t]*(?>\r\n|\r|\n)"),
              re.compile(r"\r\n|\r|\n"), re.compile(r"[?!.]+"), re.compile(r"\s+"))


@dataclass(frozen=True)
class TextChunk:
    start: int
    end: int
    text: str


def boundary(text: str, start: int, end: int, distance: int, level: int = 0) -> int:
    if distance == 0 or level == len(BOUNDARIES):
        return end
    matches = list(BOUNDARIES[level].finditer(text, max(start + 1, end - distance), end))
    if matches:
        return matches[-1].end()
    return boundary(text, start, end, distance, level + 1)


def split_text(text: str, size: int = 8000, search: int = 1000, *, offset: int = 0) -> list[TextChunk]:
    if size <= 0 or not 0 <= search < size:
        raise ValueError("Chunk size must be positive and boundary search smaller than chunk size.")
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            end = boundary(text, start, end, search)
        chunks.append(TextChunk(offset + start, offset + end, text[start:end]))
        start = end
    return chunks
