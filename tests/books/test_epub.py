from io import BytesIO
from zipfile import ZipFile

import pytest

from vysol.books import ErrorCode, ImportLimits, Upload, import_books


def convert(tmp_path, content, limits=None):
    return import_books("world", [Upload("Book.epub", content)], data_dir=tmp_path, limits=limits)[0]


def test_reading_order_all_sections_and_spacing(tmp_path, epub):
    content = epub({"last": "<p>Last chapter</p>", "nav": "<nav><h1>Contents</h1><a>First chapter</a></nav>",
                    "first": "<h1>First chapter</h1><p>Copyright notice</p><p>Hello <em>reader</em>.</p><hr/><p>Next<br/>line</p>",
                    "note": "<p>Author note</p>", "appendix": "<p>Appendix</p>"},
                   spine=["first", "last", "note"],
                   extra_manifest='<item id="css" href="style.css" media-type="text/css"/>',
                   extra_files={"EPUB/style.css": "body { color: red; }"})
    result = convert(tmp_path, content)
    assert result.error is None, result.message
    text = result.book.text_path.read_text(encoding="utf-8")
    assert text.index("Contents") < text.index("Copyright") < text.index("Last chapter") < text.index("Author note") < text.index("Appendix")
    assert "Hello reader." in text
    assert "***\n\nNext\nline" in text
    assert "Hidden title" not in text and "color" not in text
    assert text.count("Author note") == 1


def test_epub2_navigation_and_repeated_passages(tmp_path, epub):
    content = epub({"a": "<p>Repeated text</p>", "b": "<p>Repeated text</p>"}, version="2.0",
        extra_manifest='<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        extra_files={"EPUB/toc.ncx": '<ncx><navMap><navPoint><navLabel><text>Chapter label</text></navLabel></navPoint></navMap></ncx>'})
    result = convert(tmp_path, content)
    assert result.error is None
    text = result.book.text_path.read_text()
    assert text.startswith("Chapter label") and text.count("Repeated text") == 2


def test_nav_in_spine_is_not_duplicated(tmp_path, epub):
    result = convert(tmp_path, epub({"nav": "<p>Contents</p>", "a": "<p>Story</p>"}))
    assert result.book.text_path.read_text().count("Contents") == 1


def test_scripts_images_excluded_but_captions_links_kept(tmp_path, epub):
    result = convert(tmp_path, epub({"a": '<script>secret script</script><style>secret style</style><figure><img src="x"/><figcaption>Caption</figcaption></figure><p><a href="https://example.invalid">Link words</a></p>'}))
    text = result.book.text_path.read_text()
    assert "secret" not in text and "Caption" in text and "Link words" in text


@pytest.mark.parametrize("content", [b"not a zip", b"PK\x03\x04"])
def test_corrupt_epub(tmp_path, content):
    assert convert(tmp_path, content).error == ErrorCode.INVALID_EPUB


@pytest.mark.parametrize("extra_manifest,extra_files", [
    ('<item id="missing" href="missing.xhtml" media-type="application/xhtml+xml"/>', {}),
    ('<item id="bad" href="bad.md" media-type="text/markdown"/>', {"EPUB/bad.md": "Text"}),
    ('<item id="bad" href="../../escape.xhtml" media-type="application/xhtml+xml"/>', {}),
    ('<item id="bad" href="https://example.invalid/book.xhtml" media-type="application/xhtml+xml"/>', {}),
])
def test_missing_unsupported_or_unsafe_content(tmp_path, epub, extra_manifest, extra_files):
    assert convert(tmp_path, epub(extra_manifest=extra_manifest, extra_files=extra_files)).error == ErrorCode.INVALID_EPUB


def test_invalid_document_encoding(tmp_path, epub):
    content = epub(extra_manifest='<item id="bad" href="bad.xhtml" media-type="application/xhtml+xml"/>',
                   extra_files={"EPUB/bad.xhtml": b"<p>\xff</p>"})
    assert convert(tmp_path, content).error == ErrorCode.INVALID_ENCODING


@pytest.mark.parametrize("limits", [ImportLimits(max_archive_entries=2), ImportLimits(max_uncompressed_bytes=10)])
def test_archive_limits(tmp_path, epub, limits):
    assert convert(tmp_path, epub(), limits).error == ErrorCode.SIZE_LIMIT


def test_empty_book(tmp_path, epub):
    assert convert(tmp_path, epub({"a": '<img src="cover.png"/>'})).error == ErrorCode.EMPTY_BOOK


def test_xml_entities_rejected(tmp_path):
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", '<!DOCTYPE x [<!ENTITY x "bad">]><container>&x;</container>')
    assert convert(tmp_path, stream.getvalue()).error == ErrorCode.INVALID_EPUB


def test_encrypted_text_rejected(tmp_path, epub):
    content = epub(extra_files={"META-INF/encryption.xml": '<encryption><EncryptedData><CipherData><CipherReference URI="EPUB/chapter.xhtml"/></CipherData></EncryptedData></encryption>'})
    assert convert(tmp_path, content).error == ErrorCode.INVALID_EPUB


def test_guide_toc_avoids_ncx_fallback(tmp_path, epub):
    content = epub({"toc": "<p>Textual contents</p>", "story": "<p>Story</p>"}, version="2.0",
        guide='<guide><reference type="toc" href="toc.xhtml#contents"/></guide>',
        extra_manifest='<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        extra_files={"EPUB/toc.ncx": '<ncx><navMap><navPoint><navLabel><text>NCX label</text></navLabel></navPoint></navMap></ncx>'})
    result = convert(tmp_path, content)
    assert result.error is None
    assert "NCX label" not in result.book.text_path.read_text()


def test_guide_contents_outside_spine_precedes_story(tmp_path, epub):
    content = epub({"story": "<p>Story</p>", "toc": "<p>Contents</p>"}, spine=["story"], version="2.0",
                   guide='<guide><reference type="toc" href="toc.xhtml"/></guide>')
    result = convert(tmp_path, content)
    assert result.error is None
    assert result.book.text_path.read_text() == "Contents\n\nStory"


def test_unknown_spine_reference(tmp_path, epub):
    assert convert(tmp_path, epub(spine=["missing"])).error == ErrorCode.INVALID_EPUB


def test_inline_words_and_unicode(tmp_path, epub):
    result = convert(tmp_path, epub({"chapter": "<p>un<em>break</em>able &amp; café 世界.</p><p>***</p>"}))
    assert result.book.text_path.read_text(encoding="utf-8") == "unbreakable & café 世界.\n\n***"


def test_deep_markup_does_not_hit_python_recursion_limit(tmp_path, epub):
    result = convert(tmp_path, epub({"chapter": "<div>" * 1500 + "Story" + "</div>" * 1500}))
    assert result.error is None
    assert result.book.text_path.read_text() == "Story"
