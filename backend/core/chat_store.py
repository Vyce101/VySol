import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .atomic_json import dump_json_atomic
from .config import world_dir

CHAT_STORAGE_VERSION = 2
CHAT_PAGE_SIZE = 20
CHAT_INDEX_FILE = "_index.json"


class ChatVersionConflictError(RuntimeError):
    pass


class ChatStore:
    def __init__(self, world_id: str):
        self.world_id = world_id
        self.chats_dir = world_dir(world_id) / "chats"
        self.chats_dir.mkdir(parents=True, exist_ok=True)
        self._recover_legacy_temp_files()

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _index_path(self) -> Path:
        return self.chats_dir / CHAT_INDEX_FILE

    def _legacy_path(self, chat_id: str) -> Path:
        return self.chats_dir / f"{chat_id}.json"

    def _chat_dir(self, chat_id: str) -> Path:
        return self.chats_dir / chat_id

    def _chat_meta_path(self, chat_id: str) -> Path:
        return self._chat_dir(chat_id) / "meta.json"

    def _chat_pages_dir(self, chat_id: str) -> Path:
        return self._chat_dir(chat_id) / "pages"

    def _chat_page_path(self, chat_id: str, page_index: int) -> Path:
        return self._chat_pages_dir(chat_id) / f"page-{page_index + 1:06d}.json"

    def _read_json_file(self, path: Path) -> dict | None:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
        except Exception:
            return None
        return None

    def _parse_updated_at(self, data: dict | None, fallback: datetime) -> datetime:
        if not data:
            return fallback
        raw = data.get("updated_at")
        if not isinstance(raw, str):
            return fallback
        try:
            value = datetime.fromisoformat(raw)
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        except Exception:
            return fallback

    def _next_backup_path(self, canonical: Path) -> Path:
        idx = 1
        while True:
            candidate = canonical.with_suffix(f".bak{idx}")
            if not candidate.exists():
                return candidate
            idx += 1

    def _recover_legacy_temp_files(self) -> None:
        for tmp in self.chats_dir.glob("*.tmp.json"):
            canonical = tmp.with_name(tmp.name.replace(".tmp.json", ".json"))
            try:
                if not canonical.exists():
                    os.replace(str(tmp), str(canonical))
                    continue

                tmp_data = self._read_json_file(tmp)
                canonical_data = self._read_json_file(canonical)
                tmp_mtime = datetime.fromtimestamp(tmp.stat().st_mtime, tz=timezone.utc)
                canonical_mtime = datetime.fromtimestamp(canonical.stat().st_mtime, tz=timezone.utc)
                tmp_updated = self._parse_updated_at(tmp_data, tmp_mtime)
                canonical_updated = self._parse_updated_at(canonical_data, canonical_mtime)

                if tmp_updated > canonical_updated:
                    backup = self._next_backup_path(canonical)
                    os.replace(str(canonical), str(backup))
                    os.replace(str(tmp), str(canonical))
                else:
                    os.remove(tmp)
            except OSError:
                pass

        backups_by_canonical: dict[Path, list[Path]] = {}
        for bak in self.chats_dir.glob("*.bak*"):
            base = bak.name.split(".bak", 1)[0]
            if not base:
                continue
            canonical = self.chats_dir / f"{base}.json"
            backups_by_canonical.setdefault(canonical, []).append(bak)

        for canonical, backups in backups_by_canonical.items():
            if canonical.exists() or not backups:
                continue
            try:
                best_path = None
                best_updated = None
                for candidate in backups:
                    data = self._read_json_file(candidate)
                    c_mtime = datetime.fromtimestamp(candidate.stat().st_mtime, tz=timezone.utc)
                    c_updated = self._parse_updated_at(data, c_mtime)
                    if best_updated is None or c_updated > best_updated:
                        best_updated = c_updated
                        best_path = candidate

                if not best_path:
                    continue

                best_data = self._read_json_file(best_path)
                if not best_data:
                    continue

                if "id" not in best_data:
                    best_data["id"] = canonical.stem
                if "messages" not in best_data or not isinstance(best_data["messages"], list):
                    best_data["messages"] = []
                if "created_at" not in best_data:
                    best_data["created_at"] = self._now_iso()
                if "updated_at" not in best_data:
                    best_data["updated_at"] = self._now_iso()
                if "version" not in best_data:
                    best_data["version"] = 0

                dump_json_atomic(canonical, best_data)
            except OSError:
                pass

    def _normalize_message(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            payload = {}

        normalized = dict(payload)
        normalized["role"] = payload.get("role", "model")
        normalized["content"] = payload.get("content", "")
        normalized["message_id"] = payload.get("message_id") or payload.get("messageId") or str(uuid.uuid4())
        normalized["status"] = payload.get("status") or "complete"
        return normalized

    def _derive_preview_title(self, messages: list[dict]) -> str:
        for message in messages:
            if message.get("role") != "user":
                continue
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            first_line = content.splitlines()[0].strip()
            if not first_line:
                continue
            if len(first_line) > 80:
                return f"{first_line[:77].rstrip()}..."
            return first_line
        return "New Chat"

    def _legacy_autotitle_candidates(self, messages: list[dict]) -> set[str]:
        candidates = {"New Chat"}
        preview = self._derive_preview_title(messages)
        if preview:
            candidates.add(preview)
            if len(preview) > 30:
                candidates.add(f"{preview[:30]}...")
            else:
                candidates.add(preview)
        return {candidate.strip() for candidate in candidates if candidate.strip()}

    def _normalize_has_manual_title(
        self,
        raw_value: object,
        title: str,
        messages: list[dict],
    ) -> bool:
        if isinstance(raw_value, bool):
            return raw_value

        normalized_title = str(title or "").strip()
        if not normalized_title:
            return False
        return normalized_title not in self._legacy_autotitle_candidates(messages)

    def _normalize_chat(self, payload: dict | None, chat_id: str, *, now: str | None = None) -> dict:
        data = dict(payload or {})
        now_value = now or self._now_iso()

        raw_messages = data.get("messages", [])
        if not isinstance(raw_messages, list):
            raw_messages = []
        messages = [self._normalize_message(msg) for msg in raw_messages]

        version = data.get("version", 0)
        if not isinstance(version, int) or version < 0:
            version = 0

        title = str(data.get("title") or "").strip() or "New Chat"
        has_manual_title = self._normalize_has_manual_title(data.get("has_manual_title"), title, messages)
        if not has_manual_title:
            title = self._derive_preview_title(messages)

        return {
            **data,
            "id": data.get("id", chat_id),
            "title": title,
            "has_manual_title": has_manual_title,
            "created_at": data.get("created_at", now_value),
            "updated_at": data.get("updated_at", now_value),
            "version": version,
            "storage_version": CHAT_STORAGE_VERSION,
            "page_size": CHAT_PAGE_SIZE,
            "total_messages": len(messages),
            "messages": messages,
        }

    def _normalize_meta(self, payload: dict | None, chat_id: str) -> dict:
        data = dict(payload or {})
        now_value = self._now_iso()

        version = data.get("version", 0)
        if not isinstance(version, int) or version < 0:
            version = 0

        total_messages = data.get("total_messages", 0)
        if not isinstance(total_messages, int) or total_messages < 0:
            total_messages = 0

        title = str(data.get("title") or "").strip() or "New Chat"
        has_manual_title = bool(data.get("has_manual_title", False))

        return {
            "id": data.get("id", chat_id),
            "title": title,
            "has_manual_title": has_manual_title,
            "created_at": data.get("created_at", now_value),
            "updated_at": data.get("updated_at", now_value),
            "version": version,
            "storage_version": CHAT_STORAGE_VERSION,
            "page_size": CHAT_PAGE_SIZE,
            "total_messages": total_messages,
        }

    def _chat_summary_from_meta(self, meta: dict) -> dict:
        return {
            "id": meta.get("id"),
            "title": meta.get("title", "New Chat"),
            "created_at": meta.get("created_at"),
            "updated_at": meta.get("updated_at"),
            "version": meta.get("version", 0),
            "has_manual_title": bool(meta.get("has_manual_title", False)),
        }

    def _read_index(self) -> list[dict] | None:
        payload = self._read_json_file(self._index_path())
        if not payload:
            return None
        raw_chats = payload.get("chats")
        if not isinstance(raw_chats, list):
            return None
        chats: list[dict] = []
        for item in raw_chats:
            if not isinstance(item, dict):
                continue
            summary = self._chat_summary_from_meta(item)
            if summary.get("id"):
                chats.append(summary)
        return chats

    def _write_index(self, chats: list[dict]) -> None:
        deduped: list[dict] = []
        seen_ids: set[str] = set()
        for chat in sorted(chats, key=lambda item: item.get("updated_at", ""), reverse=True):
            chat_id = str(chat.get("id") or "").strip()
            if not chat_id or chat_id in seen_ids:
                continue
            seen_ids.add(chat_id)
            deduped.append({
                "id": chat_id,
                "title": chat.get("title", "New Chat"),
                "created_at": chat.get("created_at"),
                "updated_at": chat.get("updated_at"),
                "version": int(chat.get("version", 0) or 0),
                "has_manual_title": bool(chat.get("has_manual_title", False)),
            })
        dump_json_atomic(self._index_path(), {"storage_version": CHAT_STORAGE_VERSION, "chats": deduped})

    def _ensure_index(self) -> list[dict]:
        existing = self._read_index()
        if existing is not None:
            return existing

        chats: list[dict] = []

        for candidate in self.chats_dir.iterdir():
            if candidate.is_dir():
                meta = self._read_json_file(candidate / "meta.json")
                if meta:
                    normalized_meta = self._normalize_meta(meta, candidate.name)
                    chats.append(self._chat_summary_from_meta(normalized_meta))
                continue

            if candidate.name == CHAT_INDEX_FILE or not candidate.name.endswith(".json"):
                continue
            if candidate.name.endswith(".tmp.json") or ".bak" in candidate.name:
                continue

            legacy = self._read_json_file(candidate)
            if not legacy:
                continue
            normalized = self._normalize_chat(legacy, candidate.stem)
            chats.append(self._chat_summary_from_meta(normalized))

        self._write_index(chats)
        return self._read_index() or []

    def _update_index_entry(self, summary: dict) -> None:
        current = self._ensure_index()
        updated = [entry for entry in current if entry.get("id") != summary.get("id")]
        updated.append(summary)
        self._write_index(updated)

    def _remove_index_entry(self, chat_id: str) -> None:
        current = self._ensure_index()
        self._write_index([entry for entry in current if entry.get("id") != chat_id])

    def _migrate_legacy_chat(self, chat_id: str) -> None:
        legacy_path = self._legacy_path(chat_id)
        if not legacy_path.exists():
            return

        payload = self._read_json_file(legacy_path)
        if not payload:
            return

        normalized = self._normalize_chat(payload, chat_id)
        self._write_split_chat(chat_id, normalized)
        try:
            os.remove(legacy_path)
        except OSError:
            pass

    def _ensure_split_chat(self, chat_id: str) -> None:
        meta_path = self._chat_meta_path(chat_id)
        if meta_path.exists():
            return
        self._migrate_legacy_chat(chat_id)

    def _write_split_chat(self, chat_id: str, chat: dict) -> dict:
        chat_dir = self._chat_dir(chat_id)
        pages_dir = self._chat_pages_dir(chat_id)
        chat_dir.mkdir(parents=True, exist_ok=True)
        pages_dir.mkdir(parents=True, exist_ok=True)

        messages = [self._normalize_message(msg) for msg in chat.get("messages", [])]
        title = str(chat.get("title") or "New Chat").strip() or "New Chat"
        has_manual_title = bool(chat.get("has_manual_title", False))
        if not has_manual_title:
            title = self._derive_preview_title(messages)

        meta = self._normalize_meta(
            {
                **chat,
                "title": title,
                "has_manual_title": has_manual_title,
                "total_messages": len(messages),
            },
            chat_id,
        )

        for existing_page in pages_dir.glob("page-*.json"):
            try:
                existing_page.unlink()
            except OSError:
                pass

        for page_index, start in enumerate(range(0, len(messages), CHAT_PAGE_SIZE)):
            page_messages = messages[start:start + CHAT_PAGE_SIZE]
            dump_json_atomic(
                self._chat_page_path(chat_id, page_index),
                {"messages": page_messages},
            )

        dump_json_atomic(self._chat_meta_path(chat_id), meta)
        self._update_index_entry(self._chat_summary_from_meta(meta))
        return {**meta, "messages": messages}

    def _load_meta(self, chat_id: str) -> dict | None:
        self._ensure_split_chat(chat_id)
        meta = self._read_json_file(self._chat_meta_path(chat_id))
        if not meta:
            return None
        return self._normalize_meta(meta, chat_id)

    def _read_page_messages(self, chat_id: str, page_index: int) -> list[dict]:
        payload = self._read_json_file(self._chat_page_path(chat_id, page_index))
        raw_messages = payload.get("messages") if isinstance(payload, dict) else []
        if not isinstance(raw_messages, list):
            return []
        return [self._normalize_message(message) for message in raw_messages]

    def _load_all_messages(self, chat_id: str, total_messages: int | None = None) -> list[dict]:
        meta = self._load_meta(chat_id)
        if not meta:
            return []
        total = meta.get("total_messages", 0) if total_messages is None else total_messages
        if total <= 0:
            return []

        messages: list[dict] = []
        page_count = (total + CHAT_PAGE_SIZE - 1) // CHAT_PAGE_SIZE
        for page_index in range(page_count):
            messages.extend(self._read_page_messages(chat_id, page_index))
        return messages[:total]

    def _load_message_window(self, chat_id: str, start_index: int, end_index: int) -> list[dict]:
        if end_index <= start_index:
            return []

        first_page = start_index // CHAT_PAGE_SIZE
        last_page = (end_index - 1) // CHAT_PAGE_SIZE
        output: list[dict] = []

        for page_index in range(first_page, last_page + 1):
            page_messages = self._read_page_messages(chat_id, page_index)
            page_start = page_index * CHAT_PAGE_SIZE
            page_end = page_start + len(page_messages)
            overlap_start = max(start_index, page_start)
            overlap_end = min(end_index, page_end)
            if overlap_end <= overlap_start:
                continue
            local_start = overlap_start - page_start
            local_end = overlap_end - page_start
            output.extend(page_messages[local_start:local_end])

        return output

    def list_chats(self) -> list[dict]:
        return self._ensure_index()

    def create_chat(self, title: str = "New Chat") -> dict:
        chat_id = str(uuid.uuid4())
        now = self._now_iso()
        normalized_title = str(title or "").strip() or "New Chat"
        has_manual_title = normalized_title != "New Chat"
        data = {
            "id": chat_id,
            "title": normalized_title,
            "has_manual_title": has_manual_title,
            "created_at": now,
            "updated_at": now,
            "version": 0,
            "messages": [],
        }
        return self.save_chat(chat_id, data)

    def get_chat(self, chat_id: str) -> dict | None:
        meta = self._load_meta(chat_id)
        if not meta:
            return None
        messages = self._load_all_messages(chat_id, meta.get("total_messages", 0))
        return {**meta, "messages": messages}

    def get_chat_page(self, chat_id: str, *, cursor: int | None = None, page_size: int = CHAT_PAGE_SIZE) -> dict | None:
        meta = self._load_meta(chat_id)
        if not meta:
            return None

        total = int(meta.get("total_messages", 0) or 0)
        normalized_page_size = max(1, int(page_size or CHAT_PAGE_SIZE))
        offset = max(0, int(cursor or 0))
        offset = min(offset, total)

        end_index = total - offset
        start_index = max(0, end_index - normalized_page_size)
        messages = self._load_message_window(chat_id, start_index, end_index)
        loaded_count = offset + len(messages)
        has_more = start_index > 0

        return {
            **self._chat_summary_from_meta(meta),
            "version": meta.get("version", 0),
            "messages": messages,
            "has_more": has_more,
            "cursor": loaded_count if has_more else None,
            "page_size": normalized_page_size,
            "total_messages": total,
        }

    def save_chat(self, chat_id: str, data: dict, *, expected_version: int | None = None) -> dict:
        existing_meta = self._load_meta(chat_id)
        current_version = existing_meta.get("version", 0) if existing_meta else 0
        if expected_version is not None and current_version != expected_version:
            raise ChatVersionConflictError(
                f"Chat {chat_id} has version {current_version}, expected {expected_version}."
            )

        now = self._now_iso()
        normalized = self._normalize_chat(data, chat_id, now=now)
        normalized["version"] = current_version + 1
        normalized["updated_at"] = now
        return self._write_split_chat(chat_id, normalized)

    def rename_chat(self, chat_id: str, title: str, *, expected_version: int | None = None) -> dict | None:
        existing = self.get_chat(chat_id)
        if not existing:
            return None

        normalized_title = str(title).strip()
        if not normalized_title:
            raise ValueError("Chat title cannot be empty.")

        current_version = existing.get("version", 0)
        if expected_version is not None and current_version != expected_version:
            raise ChatVersionConflictError(
                f"Chat {chat_id} has version {current_version}, expected {expected_version}."
            )

        preserved_updated_at = existing.get("updated_at", self._now_iso())
        renamed = self._normalize_chat(existing, chat_id, now=preserved_updated_at)
        renamed["title"] = normalized_title
        renamed["has_manual_title"] = True
        renamed["version"] = current_version + 1
        renamed["updated_at"] = preserved_updated_at

        return self._write_split_chat(chat_id, renamed)

    def delete_chat(self, chat_id: str) -> bool:
        deleted = False
        legacy_path = self._legacy_path(chat_id)
        if legacy_path.exists():
            try:
                os.remove(legacy_path)
                deleted = True
            except OSError:
                pass

        chat_dir = self._chat_dir(chat_id)
        if chat_dir.exists():
            for child in sorted(chat_dir.rglob("*"), reverse=True):
                try:
                    if child.is_file():
                        child.unlink()
                    else:
                        child.rmdir()
                except OSError:
                    pass
            try:
                chat_dir.rmdir()
            except OSError:
                pass
            deleted = True

        if deleted:
            self._remove_index_entry(chat_id)
        return deleted
