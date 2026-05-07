from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
USER_DIRECTORY_NAME = "user"
DATA_DIRECTORY_NAME = "data"
LOG_DIRECTORY_NAME = "logs"
WORLDS_DIRECTORY_NAME = "worlds"
DATABASE_FILE_NAME = "app.sqlite"


def get_user_directory() -> Path:
    return REPO_ROOT / USER_DIRECTORY_NAME


def get_data_directory() -> Path:
    return get_user_directory() / DATA_DIRECTORY_NAME


def get_log_directory() -> Path:
    return get_user_directory() / LOG_DIRECTORY_NAME


def get_worlds_directory() -> Path:
    return get_user_directory() / WORLDS_DIRECTORY_NAME


def get_app_database_path() -> Path:
    return get_data_directory() / DATABASE_FILE_NAME
