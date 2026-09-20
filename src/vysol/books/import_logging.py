"""Batch-scoped logging with serialized file rotation across app processes."""

from contextlib import contextmanager
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
from uuid import uuid4

from filelock import FileLock, Timeout

from .storage import safe_directory

COLORS = {logging.DEBUG: "\033[34m", logging.INFO: "\033[32m",
          logging.WARNING: "\033[33m", logging.ERROR: "\033[31m",
          logging.CRITICAL: "\033[1;37;41m"}


class TerminalFormatter(logging.Formatter):
    def format(self, record):
        return COLORS.get(record.levelno, "") + super().format(record) + "\033[0m"


class LockedRotatingHandler(RotatingFileHandler):
    def emit(self, record):
        try:
            with FileLock(str(self.baseFilename) + ".lock", timeout=30):
                # Reopen under the lock so other processes can rotate safely on Windows.
                try:
                    super().emit(record)
                finally:
                    if self.stream:
                        self.stream.close()
                        self.stream = None
        except (OSError, Timeout):
            self.handleError(record)

    def handleError(self, record):
        # Logging failures must not turn a published book into a failed result or
        # expose filesystem paths through logging's default traceback handler.
        sys.stderr.write("\033[31mERROR Import file logging failed; terminal logging remains available.\033[0m\n")


@contextmanager
def import_logger(root: Path):
    logger = logging.Logger("vysol.books." + uuid4().hex, level=logging.INFO)
    terminal = logging.StreamHandler(sys.stderr)
    terminal.setFormatter(TerminalFormatter("%(levelname)s %(message)s"))
    logger.addHandler(terminal)
    disk = None
    try:
        logs = safe_directory(root, "logs")
        for path in (logs / "imports.log", logs / "imports.log.lock"):
            if path.is_symlink():
                raise OSError("Invalid logging path")
        disk = LockedRotatingHandler(logs / "imports.log", maxBytes=1024 * 1024, backupCount=10,
                                     encoding="utf-8", delay=True)
        disk.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(disk)
        yield logger
    finally:
        terminal.close()
        if disk:
            disk.close()
