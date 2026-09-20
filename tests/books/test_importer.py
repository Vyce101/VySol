from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import codecs
import json
from pathlib import Path
import subprocess

import pytest

from vysol.books import ErrorCode, ImportLimits, Upload, import_books


def read_working(result):
    assert result.error is None, result.message
    return result.book.text_path.read_bytes().decode("utf-8")


def test_separate_books_worlds_and_originals(tmp_path, epub):
    content = epub()
    uploads = [Upload("Book.epub", content), Upload("Second.txt", b"Second")]
    first = import_books("world", uploads, data_dir=tmp_path)
    second = import_books("World", uploads, data_dir=tmp_path)
    assert len({result.book.book_id for result in first + second}) == 4
    for results in (first, second):
        assert results[0].book.original_path.read_bytes() == content
        assert results[0].book.text_path.name == "Book.txt"
        assert results[1].book.original_path != results[1].book.text_path
        assert read_working(results[1]) == "Second"
        metadata = json.loads((results[0].book.original_path.parent.parent / "metadata.json").read_text())
        assert metadata["comparison_name"] == "book"
        assert metadata["converter_version"] == 1


def test_duplicate_normalization_and_batch_failures(tmp_path, epub):
    results = import_books("world", [Upload("Book.epub", epub()), Upload(" book .TXT", b"Other"),
                                    Upload("Book.Part.One.txt", b"One"), Upload("Book.Part.Two.txt", b"Two"),
                                    Upload("Broken.txt", b"\xff"), Upload("Final.txt", b"Last")], data_dir=tmp_path)
    assert [r.error for r in results] == [None, ErrorCode.DUPLICATE_NAME, None, None, ErrorCode.INVALID_ENCODING, None]
    assert "reader" in read_working(results[0])
    assert import_books("world", [Upload("Broken.txt", b"Repaired")], data_dir=tmp_path)[0].error is None


def test_unicode_casefold(tmp_path):
    results = import_books("world", [Upload("Straße.txt", b"A"), Upload("STRASSE.txt", b"B")], data_dir=tmp_path)
    assert results[1].error == ErrorCode.DUPLICATE_NAME


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "utf-32"])
def test_txt_encoding_preserves_text(tmp_path, encoding):
    text = "  Café 世界\r\n\r\nNext\tline\n"
    content = text.encode(encoding)
    result = import_books("world", [Upload("Book.txt", content)], data_dir=tmp_path)[0]
    assert read_working(result) == text
    assert result.book.original_path.read_bytes() == content
    assert not result.book.text_path.read_bytes().startswith(codecs.BOM_UTF8)


@pytest.mark.parametrize("content, code", [(b"\xff", ErrorCode.INVALID_ENCODING),
    (b"a\x00b\x00", ErrorCode.INVALID_ENCODING), (b" \r\n\t", ErrorCode.EMPTY_BOOK),
    (codecs.BOM_UTF16_LE + b"a", ErrorCode.INVALID_ENCODING)])
def test_invalid_txt_leaves_no_book(tmp_path, content, code):
    result = import_books("world", [Upload("Book.txt", content)], data_dir=tmp_path)[0]
    assert result.error == code
    assert not list(tmp_path.rglob("metadata.json"))


@pytest.mark.parametrize("name", ["../book.txt", "folder/book.txt", "folder\\book.txt", "C:book.txt", "CON.txt", ".txt", "x\x00.txt", "x\ud800.txt"])
def test_unsafe_filename(tmp_path, name):
    assert import_books("world", [Upload(name, b"Text")], data_dir=tmp_path)[0].error == ErrorCode.INVALID_INPUT


@pytest.mark.parametrize("world", ["../world", "a/b", "a\\b", "", "CON"])
def test_unsafe_world(tmp_path, world):
    assert import_books(world, [Upload("Book.txt", b"Text")], data_dir=tmp_path)[0].error == ErrorCode.INVALID_INPUT


def test_unsupported_format_and_size(tmp_path):
    assert import_books("world", [Upload("Book.pdf", b"PDF")], data_dir=tmp_path)[0].error == ErrorCode.UNSUPPORTED_FORMAT
    assert import_books("world", [Upload("Book.txt", b"1234")], data_dir=tmp_path,
                        limits=ImportLimits(max_upload_bytes=3))[0].error == ErrorCode.SIZE_LIMIT


def test_write_failure_rolls_back_and_retry_succeeds(tmp_path, monkeypatch):
    original = Path.write_bytes
    def fail_working(path, content):
        if path.parent.name == "text":
            raise OSError("Simulated full disk")
        return original(path, content)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "write_bytes", fail_working)
        result = import_books("world", [Upload("Book.txt", b"Text")], data_dir=tmp_path)[0]
    assert result.error == ErrorCode.STORAGE_FAILURE
    assert not list(tmp_path.rglob("metadata.json"))
    assert list((tmp_path / "staging").iterdir()) == []
    assert import_books("world", [Upload("Book.txt", b"Text")], data_dir=tmp_path)[0].error is None


def concurrent_import(root):
    return import_books("world", [Upload("Book.txt", b"Text")], data_dir=root)[0].error


@pytest.mark.parametrize("executor", [ThreadPoolExecutor, ProcessPoolExecutor])
def test_concurrent_duplicates(tmp_path, executor):
    with executor(max_workers=4) as pool:
        errors = list(pool.map(concurrent_import, [tmp_path] * 4))
    assert errors.count(None) == 1
    assert errors.count(ErrorCode.DUPLICATE_NAME) == 3
    assert len(list(tmp_path.rglob("metadata.json"))) == 1


def test_unavailable_storage(tmp_path):
    target = tmp_path / "file"
    target.write_bytes(b"not a directory")
    result = import_books("world", [Upload("Book.txt", b"Text")], data_dir=target)[0]
    assert result.error == ErrorCode.STORAGE_FAILURE


def test_logs_do_not_include_private_names_or_content(tmp_path, capsys):
    import_books("world", [Upload("Private title.txt", b"Secret story"), Upload("Bad.txt", b"\xff")], data_dir=tmp_path)
    terminal = capsys.readouterr().err
    logs = (tmp_path / "logs" / "imports.log").read_text()
    assert "\033[32m" in terminal and "\033[33m" in terminal
    for output in (terminal, logs):
        assert "Private title" not in output and "Secret story" not in output
        assert "succeeded" in output and "invalid_encoding" in output


def test_runtime_files_are_git_ignored():
    repo = Path(__file__).resolve().parents[2]
    paths = ["data/worlds/a/books/b/original/book.epub", "data/staging/test/file.txt", "data/logs/imports.log"]
    result = subprocess.run(["git", "check-ignore", *paths], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout.splitlines() == paths
