"""Local plaintext credentials, isolated from metadata and ignored by Git."""

import os
from pathlib import Path
import tempfile
from typing import Protocol
from uuid import UUID


class CredentialVault(Protocol):
    def read(self, key: str) -> str | None: ...
    def write(self, key: str, secret: str) -> None: ...
    def delete(self, key: str) -> None: ...


class FileCredentialVault:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _directory(self) -> Path:
        folder = self.root / "credentials"
        if folder.is_symlink() or folder.is_junction():
            raise OSError("Invalid credential storage directory.")
        folder.mkdir(parents=True, exist_ok=True)
        ignore = folder / ".gitignore"
        if ignore.is_symlink():
            raise OSError("Invalid credential storage ignore file.")
        # Also protect a custom runtime location that happens to be in a repository.
        with ignore.open("w", encoding="utf-8") as target:
            target.write("*\n")
        return folder

    def _target(self, key: str) -> Path:
        filename = str(UUID(key)) + ".key"
        target = self._directory() / filename
        if target.is_symlink():
            raise OSError("Invalid credential storage file.")
        return target

    def read(self, key: str) -> str | None:
        try:
            return self._target(key).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def write(self, key: str, secret: str) -> None:
        target = self._target(key)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                             prefix=".key-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(secret)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def delete(self, key: str) -> None:
        self._target(key).unlink(missing_ok=True)
