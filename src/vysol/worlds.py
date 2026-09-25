"""Persistent world identities and application preferences, separate from book data."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

from filelock import FileLock

from .books.storage import safe_directory


def _timestamp_value(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


def latest_timestamp(*values: str | None) -> str | None:
    valid = [(parsed, value) for value in values if (parsed := _timestamp_value(value)) is not None]
    return max(valid, key=lambda item: item[0])[1] if valid else None


def _world_activity_key(world: dict) -> tuple[datetime, str]:
    activity = latest_timestamp(world.get("created_at"), world.get("last_used_at"))
    parsed = _timestamp_value(activity)
    return parsed or datetime.min.replace(tzinfo=timezone.utc), world["id"]


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

    def list_worlds(self, chronicle_activity: dict[str, str] | None = None) -> list[dict]:
        worlds = []
        for path in (self.root / "worlds").glob("*/world.json"):
            if not path.resolve().is_relative_to(self.root):
                raise OSError("Invalid world storage")
            world = json.loads(path.read_text(encoding="utf-8"))
            world["book_count"] = len(self.books(world["id"]))
            world["last_used_at"] = latest_timestamp(
                world.get("last_used_at"), (chronicle_activity or {}).get(world["id"]),
            )
            worlds.append(world)
        return sorted(worlds, key=_world_activity_key, reverse=True)

    def record_activity(self, world_id: str, at: str | None = None) -> dict | None:
        """Save the latest use time without allowing older events to move a World back."""
        activity = at or datetime.now(timezone.utc).isoformat()
        if _timestamp_value(activity) is None:
            raise ValueError("World activity must be an ISO timestamp.")
        with FileLock(self.root / "locks" / "worlds.lock", timeout=30):
            try:
                world = self.get(world_id)
            except FileNotFoundError:
                return None
            world["last_used_at"] = latest_timestamp(world.get("last_used_at"), activity)
            atomic_json(self.directory(world_id) / "world.json", world)
            return world

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
            return {"background_speed": "normal", "world_layout": "shelf", "chat_appearance": "focused"}
        return {"background_speed": "normal", "world_layout": "shelf", "chat_appearance": "focused",
                **json.loads(path.read_text(encoding="utf-8"))}

    def save_settings(self, speed: str, layout: str | None = None, chat_appearance: str | None = None) -> dict:
        with FileLock(self.root / "locks" / "settings.lock", timeout=30):
            value = {**self.settings(), "background_speed": speed}
            if layout is not None:
                value["world_layout"] = layout
            if chat_appearance is not None:
                value["chat_appearance"] = chat_appearance
            atomic_json(self.root / "settings.json", value)
            return value
