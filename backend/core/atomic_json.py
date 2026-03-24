"""Shared atomic JSON writes with Windows-friendly replace retries."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

_PATH_LOCKS: dict[str, threading.Lock] = {}
_PATH_LOCKS_GUARD = threading.Lock()
_RETRYABLE_WINDOWS_ERRORS = {5, 32}


def _lock_for(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _PATH_LOCKS[key] = lock
        return lock


def _is_retryable_replace_error(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    winerror = getattr(exc, "winerror", None)
    return isinstance(winerror, int) and winerror in _RETRYABLE_WINDOWS_ERRORS


def dump_json_atomic(
    path: Path,
    payload: Any,
    *,
    retries: int = 5,
    retry_delay_seconds: float = 0.05,
) -> None:
    """Write JSON to `path` atomically with unique temp files and retryable replace."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock_for(target)

    with lock:
        for attempt in range(max(0, int(retries)) + 1):
            tmp = target.with_name(f"{target.name}.{uuid4().hex}.tmp")
            try:
                with open(tmp, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, indent=2)
                os.replace(str(tmp), str(target))
                return
            except Exception as exc:
                try:
                    if tmp.exists():
                        tmp.unlink()
                except OSError:
                    pass
                if _is_retryable_replace_error(exc) and attempt < retries:
                    time.sleep(retry_delay_seconds * (attempt + 1))
                    continue
                raise
