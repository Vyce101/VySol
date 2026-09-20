"""Strict decoding for original TXT files and UTF-8 working copies."""

import codecs

from .models import ErrorCode, ImportFailure


def decode_text(content: bytes) -> str:
    encoding = "utf-8-sig"
    if content.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        encoding = "utf-32"
    elif content.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        encoding = "utf-16"
    try:
        text = content.decode(encoding, errors="strict")
    except UnicodeError as exc:
        raise ImportFailure(
            ErrorCode.INVALID_ENCODING,
            "Cannot decode this text. Supply UTF-8 or UTF-16/UTF-32 with an encoding marker.",
        ) from exc
    if "\x00" in text:
        raise ImportFailure(ErrorCode.INVALID_ENCODING, "Text contains null characters; supply UTF-8.")
    return text
