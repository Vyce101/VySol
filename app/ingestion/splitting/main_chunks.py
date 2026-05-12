from collections.abc import Iterator
from dataclasses import dataclass

from app.draft_worlds.splitter_settings import SplitterSettings
from app.ingestion.splitting.split_points import find_next_split_index
from app.logger import get_logger

logger = get_logger()


class MainChunkGenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class MainChunk:
    chunk_number: int
    chunk_text: str
    overlap_text: str
    character_start_offset: int
    character_end_offset: int


def generate_main_chunks(
    parsed_text: str,
    splitter_settings: SplitterSettings,
) -> list[MainChunk]:
    return list(iter_main_chunks(parsed_text, splitter_settings))


def iter_main_chunks(
    parsed_text: str,
    splitter_settings: SplitterSettings,
) -> Iterator[MainChunk]:
    remaining_text = parsed_text
    consumed_character_count = 0
    completed_chunk_count = 0

    while remaining_text:
        split_index = find_safe_split_index(
            remaining_text,
            splitter_settings,
            completed_chunk_count,
        )
        chunk_text = remaining_text[:split_index]
        character_start_offset = consumed_character_count
        character_end_offset = character_start_offset + len(chunk_text)
        overlap_text = get_previous_overlap_text(
            parsed_text,
            character_start_offset,
            splitter_settings.overlap_size,
        )

        if chunk_text != "":
            completed_chunk_count += 1
            yield MainChunk(
                chunk_number=completed_chunk_count,
                chunk_text=chunk_text,
                overlap_text=overlap_text,
                character_start_offset=character_start_offset,
                character_end_offset=character_end_offset,
            )

        consumed_character_count += split_index
        remaining_text = remaining_text[split_index:]

    logger.debug("Generated main chunks: count=%s", completed_chunk_count)


def get_previous_overlap_text(
    parsed_text: str,
    character_start_offset: int,
    overlap_size: int,
) -> str:
    overlap_start_offset = max(0, character_start_offset - overlap_size)
    return parsed_text[overlap_start_offset:character_start_offset]


def find_safe_split_index(
    text: str,
    splitter_settings: SplitterSettings,
    completed_chunk_count: int,
) -> int:
    try:
        split_index = find_next_split_index(
            text,
            splitter_settings.chunk_size,
            splitter_settings.max_lookback_size,
        )
    except Exception as error:
        logger.error(
            "Unexpected splitter failure during main chunk generation.",
            exc_info=True,
        )
        raise MainChunkGenerationError(
            "Unexpected splitter failure during main chunk generation."
        ) from error

    if 0 < split_index <= len(text):
        return split_index

    logger.error(
        "Invalid split index during main chunk generation: "
        "split_index=%s remaining_length=%s completed_chunk_count=%s",
        split_index,
        len(text),
        completed_chunk_count,
    )
    raise MainChunkGenerationError("Invalid split index during main chunk generation.")
