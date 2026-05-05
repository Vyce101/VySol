import logging
import sys
from pathlib import Path

from app.storage.paths import get_log_directory

LOGGER_NAME = "vysol"
MAX_LOG_FILES = 10
CURRENT_LOG_INDEX = 0

LEVEL_COLORS = {
    logging.DEBUG: "\033[34m",
    logging.INFO: "\033[32m",
    logging.WARNING: "\033[33m",
    logging.ERROR: "\033[31m",
    logging.CRITICAL: "\033[1;37;41m",
}

RESET_COLOR = "\033[0m"


class ColorFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        color = LEVEL_COLORS.get(record.levelno, "")
        if not color:
            return formatted

        return f"{color}{formatted}{RESET_COLOR}"


def get_logger(name: str = LOGGER_NAME) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")
    terminal_formatter = ColorFormatter("[%(asctime)s] [%(levelname)s] %(message)s")

    terminal_handler = logging.StreamHandler(sys.stdout)
    terminal_handler.setLevel(logging.DEBUG)
    terminal_handler.setFormatter(terminal_formatter)

    file_handler = logging.FileHandler(prepare_log_file(), encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    logger.addHandler(terminal_handler)
    logger.addHandler(file_handler)

    return logger


def prepare_log_file() -> Path:
    log_directory = get_log_directory()
    log_directory.mkdir(parents=True, exist_ok=True)
    rotate_log_files(log_directory)

    return log_directory / f"logs_{CURRENT_LOG_INDEX}.txt"


def rotate_log_files(log_directory: Path) -> None:
    oldest_log = log_directory / f"logs_{MAX_LOG_FILES - 1}.txt"
    if oldest_log.exists():
        oldest_log.unlink()

    for index in range(MAX_LOG_FILES - 2, -1, -1):
        source = log_directory / f"logs_{index}.txt"
        destination = log_directory / f"logs_{index + 1}.txt"
        if source.exists():
            source.replace(destination)
