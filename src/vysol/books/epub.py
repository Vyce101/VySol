"""Extract publication text without executing markup or fetching resources."""

import codecs
from io import BytesIO
import posixpath
import re
from urllib.parse import unquote, urlsplit
from zipfile import BadZipFile, ZipFile
import zlib

from bs4 import BeautifulSoup, NavigableString, Tag
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from xml.etree.ElementTree import ParseError

from .models import ErrorCode, ImportFailure, ImportLimits

TEXT_TYPES = {"application/xhtml+xml", "text/html", "text/plain", "image/svg+xml"}
BLOCKS = {"p", "div", "section", "article", "header", "footer", "nav", "aside",
          "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "figure",
          "figcaption", "dl", "dt", "dd", "tr", "pre"}


def invalid(message: str) -> ImportFailure:
    return ImportFailure(ErrorCode.INVALID_EPUB, message)


def resource_path(base: str, href: str) -> str:
    url = urlsplit(href)
    path = unquote(url.path)
    if url.scheme or url.netloc or "\\" in path or path.startswith("/"):
        raise invalid("EPUB references an unsafe or external content resource.")
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(base), path))
    if resolved == ".." or resolved.startswith("../"):
        raise invalid("EPUB resource escapes the publication archive.")
    return resolved


def decode_markup(content: bytes) -> str:
    try:
        encoding = "utf-8-sig"
        if content.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
            encoding = "utf-32"
        elif content.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            encoding = "utf-16"
        else:
            declaration = re.match(br"\s*<\?xml[^>]*encoding=['\"]([^'\"]+)", content)
            if declaration:
                encoding = declaration[1].decode("ascii")
        text = content.decode(encoding, errors="strict")
        if "\x00" in text:
            raise UnicodeError("Null characters in text")
        return text
    except (UnicodeError, LookupError) as exc:
        raise ImportFailure(ErrorCode.INVALID_ENCODING, "An EPUB text document cannot be decoded.") from exc


def markup_text(content: bytes) -> str:
    soup = BeautifulSoup(decode_markup(content), "html.parser")
    for element in soup.find_all(["script", "style", "head", "img"]):
        element.decompose()
    pieces: list[str] = []

    pending = [(soup.body or soup, False, False)]
    while pending:
        node, preformatted, closing = pending.pop()
        if closing:
            if node.name.lower() in {"td", "th"}:
                pieces.append("\t")
            if node.name.lower() in BLOCKS:
                pieces.append("\n\n")
            continue
        if type(node) is NavigableString:
            pieces.append(str(node) if preformatted else re.sub(r"\s+", " ", str(node)))
            continue
        if not isinstance(node, Tag):
            continue
        name = node.name.lower()
        if name == "hr":
            pieces.append("\n\n***\n\n")
            continue
        if name == "br":
            pieces.append("\n")
            continue
        if name in BLOCKS:
            pieces.append("\n\n")
        pending.append((node, preformatted, True))
        pending.extend((child, preformatted or name == "pre", False) for child in reversed(node.contents))
    text = "".join(pieces)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_epub(content: bytes, limits: ImportLimits) -> str:
    try:
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > limits.max_archive_entries or sum(e.file_size for e in entries) > limits.max_uncompressed_bytes:
                raise ImportFailure(ErrorCode.SIZE_LIMIT, "EPUB exceeds archive expansion limits.")
            names = [e.filename for e in entries]
            if len(names) != len(set(names)):
                raise invalid("EPUB contains ambiguous duplicate archive entries.")
            for entry in entries:
                resource_path("", entry.filename)

            def read(path: str) -> bytes:
                try:
                    return archive.read(path)
                except KeyError as exc:
                    raise invalid("EPUB is missing a referenced content resource.") from exc

            if read("mimetype") != b"application/epub+zip":
                raise invalid("Archive is not an EPUB publication.")
            container = ElementTree.fromstring(read("META-INF/container.xml"))
            roots = container.findall(".//{*}rootfile")
            if len(roots) != 1:
                raise invalid("EPUB must declare one supported publication package.")
            package_path = resource_path("", roots[0].get("full-path", ""))
            package = ElementTree.fromstring(read(package_path))
            if package.get("version") not in {"2.0", "3.0"}:
                raise invalid("Unsupported EPUB package version.")
            manifest = package.find("{*}manifest")
            spine = package.find("{*}spine")
            if manifest is None or spine is None or not len(spine):
                raise invalid("EPUB has no usable manifest or reading order.")
            items = {}
            for item in manifest:
                identifier = item.get("id")
                if not identifier or identifier in items or not item.get("href"):
                    raise invalid("EPUB manifest contains an invalid or duplicate item.")
                items[identifier] = item
            ordered = []
            for ref in spine:
                item = items.get(ref.get("idref"))
                if item is None:
                    raise invalid("EPUB reading order references an unknown item.")
                media = item.get("media-type", "")
                if media not in TEXT_TYPES and not media.startswith(("image/", "audio/", "video/")):
                    raise invalid("EPUB contains unsupported reading-order content.")
                ordered.append(item)
            navigation = [item for item in items.values() if "nav" in item.get("properties", "").split()]
            guide_toc = package.findall("{*}guide/{*}reference[@type='toc']")
            toc_paths = {resource_path(package_path, ref.get("href", "")) for ref in guide_toc}
            content_paths = {resource_path(package_path, item.get("href"))
                             for item in items.values() if item.get("media-type") in TEXT_TYPES}
            if not toc_paths.issubset(content_paths) or any(item.get("media-type") not in TEXT_TYPES for item in navigation):
                raise invalid("EPUB navigation references missing or unsupported text content.")
            # Font obfuscation does not matter for TXT, but encrypted text cannot be skipped.
            if "META-INF/encryption.xml" in names:
                encryption = ElementTree.fromstring(read("META-INF/encryption.xml"))
                encrypted = {resource_path("", ref.get("URI", ""))
                             for ref in encryption.findall(".//{*}CipherReference")}
                if encrypted & content_paths:
                    raise invalid("EPUB contains encrypted text content.")
            has_text_toc = bool(navigation or toc_paths)
            parts = []
            if not has_text_toc:
                ncx = items.get(spine.get("toc"))
                if ncx is not None:
                    tree = ElementTree.fromstring(read(resource_path(package_path, ncx.get("href"))))
                    labels = ["".join(label.itertext()).strip() for label in tree.findall(".//{*}navMap//{*}navLabel/{*}text")]
                    parts.append("\n".join(labels))
            navigation = [item for item in items.values() if item in navigation
                          or (item.get("media-type") in TEXT_TYPES
                              and resource_path(package_path, item.get("href")) in toc_paths)]
            sequence = [item for item in navigation if item not in ordered] + ordered + list(items.values())
            seen = set()
            for item in sequence:
                media = item.get("media-type", "")
                if media not in TEXT_TYPES:
                    if media.startswith("text/") and media not in {"text/css", "text/javascript"}:
                        raise invalid("EPUB contains an unsupported text resource.")
                    continue
                path = resource_path(package_path, item.get("href"))
                if path in seen:
                    continue
                seen.add(path)
                raw = read(path)
                parts.append(decode_markup(raw) if media == "text/plain" else markup_text(raw))
            return "\n\n".join(part for part in parts if part.strip())
    except ImportFailure:
        raise
    except (BadZipFile, ParseError, DefusedXmlException, RuntimeError, NotImplementedError,
            ValueError, OSError, EOFError, zlib.error) as exc:
        raise invalid("EPUB is corrupt, encrypted, or has invalid package metadata.") from exc
