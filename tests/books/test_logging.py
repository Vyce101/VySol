from vysol.books import Upload, import_books
from vysol.books.import_logging import LockedRotatingHandler, import_logger


def test_rotation_retains_at_most_ten_previous_logs(tmp_path):
    with import_logger(tmp_path) as logger:
        disk = next(handler for handler in logger.handlers if isinstance(handler, LockedRotatingHandler))
        disk.maxBytes = 80
        for index in range(20):
            logger.info("Import finished batch_index=%d", index)
    files = list((tmp_path / "logs").glob("imports.log.*"))
    backups = [path for path in files if path.suffix[1:].isdigit()]
    assert len(backups) == 10
    assert (tmp_path / "logs" / "imports.log").exists()


def test_logging_failure_does_not_change_success(tmp_path, monkeypatch, capsys):
    def fail_open(self):
        raise OSError("Private path should not be logged")
    monkeypatch.setattr(LockedRotatingHandler, "_open", fail_open)
    results = import_books("world", [Upload("Book.txt", b"Text")], data_dir=tmp_path)
    assert len(results) == 1 and results[0].book is not None
    terminal = capsys.readouterr().err
    assert "file logging failed" in terminal
    assert "Private path" not in terminal
