from collections.abc import Sequence
from dataclasses import dataclass
from typing import NoReturn

from app.ingestion.attempt_workspace import TemporaryIngestionWorkspace
from app.ingestion.parsing.router import (
    EXPECTED_PARSER_ERRORS,
    StagedSource,
    UnsupportedSourceTypeError,
    parse_staged_source,
)
from app.ingestion.staging.source_staging_state import TemporarySourceStagingEntry
from app.logger import get_logger

logger = get_logger()


EXPECTED_PARSE_PREPARATION_ERRORS = (
    *EXPECTED_PARSER_ERRORS,
    UnsupportedSourceTypeError,
)


class ParsedSourcePreparationError(RuntimeError):
    pass


class UnusableParsedSourceTextError(ValueError):
    pass


@dataclass(frozen=True)
class TemporaryParsedSourceOutput:
    attempt_id: str
    staging_entry_id: str
    source_file_type: str
    parsed_text: str


def prepare_parsed_source_outputs(
    workspace: TemporaryIngestionWorkspace,
    entries: Sequence[TemporarySourceStagingEntry],
) -> tuple[TemporaryParsedSourceOutput, ...]:
    parsed_outputs: list[TemporaryParsedSourceOutput] = []

    for entry in entries:
        parsed_outputs.append(prepare_parsed_source_output(workspace, entry))

    return tuple(parsed_outputs)


def prepare_parsed_source_output(
    workspace: TemporaryIngestionWorkspace,
    entry: TemporarySourceStagingEntry,
) -> TemporaryParsedSourceOutput:
    try:
        parsed_source = parse_staged_source(
            StagedSource(
                source_file_path=entry.source_file_path,
                source_file_type=entry.source_file_type,
            )
        )
        reject_unusable_parsed_text(workspace, entry, parsed_source.parsed_text)
    except UnusableParsedSourceTextError:
        raise
    except EXPECTED_PARSE_PREPARATION_ERRORS:
        logger.warning(
            "Rejected staged source during parse preparation: "
            "attempt_id=%s staging_entry_id=%s source_type=%s",
            workspace.attempt_id,
            entry.staging_entry_id,
            entry.source_file_type,
        )
        raise
    except Exception as error:
        logger.error(
            "Unexpected parsed source preparation failure: "
            "attempt_id=%s staging_entry_id=%s source_type=%s error_type=%s",
            workspace.attempt_id,
            entry.staging_entry_id,
            entry.source_file_type,
            type(error).__name__,
        )
        raise ParsedSourcePreparationError(
            "Unexpected parsed source preparation failure."
        ) from error

    logger.info(
        "Prepared parsed source output: "
        "attempt_id=%s staging_entry_id=%s source_type=%s character_count=%s",
        workspace.attempt_id,
        entry.staging_entry_id,
        parsed_source.source_file_type,
        len(parsed_source.parsed_text),
    )
    return TemporaryParsedSourceOutput(
        attempt_id=workspace.attempt_id,
        staging_entry_id=entry.staging_entry_id,
        source_file_type=parsed_source.source_file_type,
        parsed_text=parsed_source.parsed_text,
    )


def reject_unusable_parsed_text(
    workspace: TemporaryIngestionWorkspace,
    entry: TemporarySourceStagingEntry,
    parsed_text: str,
) -> None:
    if type(parsed_text) is str and parsed_text.strip():
        return

    reject_unusable_source(workspace, entry)


def reject_unusable_source(
    workspace: TemporaryIngestionWorkspace,
    entry: TemporarySourceStagingEntry,
) -> NoReturn:
    logger.warning(
        "Rejected staged source with no usable parsed text: "
        "attempt_id=%s staging_entry_id=%s source_type=%s",
        workspace.attempt_id,
        entry.staging_entry_id,
        entry.source_file_type,
    )
    raise UnusableParsedSourceTextError(
        "Staged source did not parse into usable text."
    )
