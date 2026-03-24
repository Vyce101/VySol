import json
import os
from pathlib import Path
from types import SimpleNamespace

from core import atomic_json


def test_dump_json_atomic_retries_windows_replace_collision(monkeypatch):
    replace_calls = {"count": 0}
    real_replace = os.replace
    root = Path(__file__).resolve().parents[2] / ".vysol-pytest" / "atomic-json-case"
    target = root / "meta.json"

    def flaky_replace(src: str, dst: str) -> None:
        replace_calls["count"] += 1
        if replace_calls["count"] == 1:
            raise PermissionError(5, "Access is denied")
        real_replace(src, dst)

    monkeypatch.setattr(atomic_json, "os", SimpleNamespace(replace=flaky_replace))
    monkeypatch.setattr(atomic_json.time, "sleep", lambda seconds: None)

    root.mkdir(parents=True, exist_ok=True)
    for stale_path in [target, *root.glob("*.tmp")]:
        if stale_path.exists():
            stale_path.unlink()

    try:
        atomic_json.dump_json_atomic(target, {"status": "ok"}, retries=2, retry_delay_seconds=0)
        assert replace_calls["count"] == 2
        assert json.loads(target.read_text(encoding="utf-8")) == {"status": "ok"}
        assert list(root.glob("*.tmp")) == []
    finally:
        for stale_path in [target, *root.glob("*.tmp")]:
            if stale_path.exists():
                stale_path.unlink()
        if root.exists() and not any(root.iterdir()):
            root.rmdir()
