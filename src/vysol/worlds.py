"""Persistent world identities and application preferences, separate from book data."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

from filelock import FileLock

from .books.storage import safe_directory


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class WorldStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        safe_directory(self.root, "locks")

    def directory(self, world_id: str) -> Path:
        UUID(world_id)
        key = hashlib.sha256(world_id.encode()).hexdigest()
        return self.root / "worlds" / key

    def get(self, world_id: str) -> dict:
        path = self.directory(world_id) / "world.json"
        if not path.resolve().is_relative_to(self.root):
            raise OSError("Invalid world storage")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_worlds(self) -> list[dict]:
        worlds = []
        for path in (self.root / "worlds").glob("*/world.json"):
            if not path.resolve().is_relative_to(self.root):
                raise OSError("Invalid world storage")
            world = json.loads(path.read_text(encoding="utf-8"))
            world["book_count"] = len(self.books(world["id"]))
            worlds.append(world)
        return sorted(worlds, key=lambda w: (bool(w.get("last_used_at")), w.get("last_used_at") or w["created_at"], w["id"]), reverse=True)

    def create(self, world_id: str, name: str) -> dict:
        with FileLock(self.root / "locks" / "worlds.lock", timeout=30):
            try:
                return self.get(world_id)
            except FileNotFoundError:
                pass
            directory = self.directory(world_id)
            safe_directory(self.root, "worlds", directory.name)
            world = {"id": world_id, "name": name, "created_at": datetime.now(timezone.utc).isoformat(),
                     "last_used_at": None, "artwork": "frostwake"}
            atomic_json(directory / "world.json", world)
            return world

    def books(self, world_id: str) -> list[dict]:
        self.get(world_id)
        records = []
        for path in (self.directory(world_id) / "books").glob("*/metadata.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            records.append({"id": record["book_id"], "filename": record["original_filename"],
                            "comparison_name": record["comparison_name"], "position": record.get("position")})
        return sorted(records, key=lambda book: (
            book["position"] is None,
            book["position"] if book["position"] is not None else book["comparison_name"].casefold(),
        ))

    def original_digest(self, world_id: str, book: dict) -> str:
        key = hashlib.sha256(book["comparison_name"].encode()).hexdigest()
        path = self.directory(world_id) / "books" / key / "original" / book["filename"]
        if not path.resolve().is_relative_to(self.root):
            raise OSError("Invalid book storage")
        with path.open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest()

    def settings(self) -> dict:
        path = self.root / "settings.json"
        if not path.exists():
            return {"background_speed": "normal", "world_layout": "shelf"}
        return {"background_speed": "normal", "world_layout": "shelf", **json.loads(path.read_text(encoding="utf-8"))}

    def save_settings(self, speed: str, layout: str | None = None) -> dict:
        with FileLock(self.root / "locks" / "settings.lock", timeout=30):
            value = {**self.settings(), "background_speed": speed}
            if layout is not None:
                value["world_layout"] = layout
            atomic_json(self.root / "settings.json", value)
            return value
