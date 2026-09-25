"""Persistent Chronicle conversations, shared chat settings, and grounded generation."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
from pathlib import Path
import sqlite3
import struct
import threading
import time
from uuid import uuid4

import httpx
from filelock import Timeout

from .creation_store import CreationConflict
from .embeddings import DIMENSIONS, EmbeddingFailure, ProcessingPaused


CHAT_MODELS = [
    {"id": "gemini-3.8-flash", "name": "Gemini 3.8 Flash", "provider": "google", "series": "Flash"},
    {"id": "gemini-3.5-flash-lite", "name": "Gemini 3.5 Flash-Lite", "provider": "google", "series": "Flash Lite"},
    {"id": "gemma-4-31b-it", "name": "Gemma 4 31B IT", "provider": "google", "series": "Gemma"},
]
CHAT_MODEL_IDS = {model["id"] for model in CHAT_MODELS}
DEFAULT_SETTINGS = {
    "model": "gemini-3.8-flash",
    "key_id": "",
    "chunk_count": 3,
    "minimum_similarity": 0.60,
    "chunk_overlap": 150,
    "streaming_speed": 50,
    "chat_history_prefix": "<chat_history>",
    "chat_history_suffix": "</chat_history>",
    "rag_chunks_prefix": "<rag_chunks>",
    "rag_chunks_suffix": "</rag_chunks>",
    "sections": {"ai": True, "retrieval": True, "response": True, "section_tags": True},
}
TERMINAL_GENERATION_STATES = {"completed", "stopped", "failed"}


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChronicleStore:
    """SQLite storage for Chronicle rows, message history, generation IDs, and shared settings."""

    def __init__(self, path: Path):
        self.path = path
        if path.is_symlink():
            raise OSError("Invalid Chronicle storage.")
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS chronicles(
                    id TEXT PRIMARY KEY,
                    world_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_message_at TEXT
                );
                CREATE INDEX IF NOT EXISTS chronicles_by_world ON chronicles(world_id, created_at);
                CREATE TABLE IF NOT EXISTS chronicle_messages(
                    id TEXT PRIMARY KEY,
                    chronicle_id TEXT NOT NULL REFERENCES chronicles(id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                    text TEXT NOT NULL DEFAULT '',
                    thinking TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    request_id TEXT,
                    UNIQUE(chronicle_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS chronicle_messages_order
                    ON chronicle_messages(chronicle_id, sequence);
                CREATE TABLE IF NOT EXISTS chronicle_generations(
                    chronicle_id TEXT NOT NULL REFERENCES chronicles(id) ON DELETE CASCADE,
                    request_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    user_message_id TEXT NOT NULL,
                    assistant_message_id TEXT NOT NULL,
                    settings TEXT NOT NULL,
                    error_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(chronicle_id, request_id)
                );
                CREATE INDEX IF NOT EXISTS chronicle_generations_active
                    ON chronicle_generations(chronicle_id, status);
                CREATE TABLE IF NOT EXISTS chronicle_preferences(
                    id TEXT PRIMARY KEY CHECK(id='shared'),
                    data TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, world_id: str) -> dict:
        value = {"id": str(uuid4()), "world_id": world_id, "title": "New Chronicle",
                 "created_at": timestamp(), "last_message_at": None}
        with self.connect() as db:
            db.execute("INSERT INTO chronicles(id,world_id,title,created_at,last_message_at) VALUES(?,?,?,?,NULL)",
                       (value["id"], world_id, value["title"], value["created_at"]))
        return self.summary(value["id"])

    def get(self, chronicle_id: str, *, db=None) -> dict | None:
        if db is None:
            with self.connect() as connection:
                return self.get(chronicle_id, db=connection)
        row = db.execute("SELECT * FROM chronicles WHERE id=?", (chronicle_id,)).fetchone()
        return dict(row) if row else None

    def require(self, chronicle_id: str, *, db=None) -> dict:
        value = self.get(chronicle_id, db=db)
        if value is None:
            raise KeyError(chronicle_id)
        return value

    def list(self, world_id: str) -> list[dict]:
        with self.connect() as db:
            ids = [row[0] for row in db.execute(
                "SELECT id FROM chronicles WHERE world_id=? "
                "ORDER BY COALESCE(last_message_at,created_at) DESC, created_at DESC, id", (world_id,))]
        return [self.summary(identity) for identity in ids]

    def world_activity(self) -> dict[str, str]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT world_id, MAX(last_message_at) AS last_message_at "
                "FROM chronicles WHERE last_message_at IS NOT NULL GROUP BY world_id"
            )
            return {row["world_id"]: row["last_message_at"] for row in rows}

    def summary(self, chronicle_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("""
                SELECT c.*, COUNT(m.id) AS message_count
                FROM chronicles c LEFT JOIN chronicle_messages m ON m.chronicle_id=c.id
                WHERE c.id=? GROUP BY c.id
            """, (chronicle_id,)).fetchone()
            if row is None:
                raise KeyError(chronicle_id)
            latest = db.execute(
                "SELECT text FROM chronicle_messages WHERE chronicle_id=? AND trim(text)<>'' "
                "ORDER BY sequence DESC LIMIT 1", (chronicle_id,)).fetchone()
            value = dict(row)
        preview = " ".join(latest["text"].split()) if latest else "No messages yet"
        value["preview"] = preview[:177].rstrip() + "…" if len(preview) > 180 else preview
        value["not_started"] = value["last_message_at"] is None
        return value

    def rename(self, chronicle_id: str, title: str) -> dict:
        with self.connect() as db:
            cursor = db.execute("UPDATE chronicles SET title=? WHERE id=?", (title, chronicle_id))
            if cursor.rowcount == 0:
                raise KeyError(chronicle_id)
        return self.summary(chronicle_id)

    def delete(self, chronicle_id: str) -> bool:
        with self.connect() as db:
            cursor = db.execute("DELETE FROM chronicles WHERE id=?", (chronicle_id,))
            return cursor.rowcount > 0

    def messages(self, chronicle_id: str) -> list[dict]:
        with self.connect() as db:
            return [self.message(row) for row in db.execute(
                "SELECT m.*, g.settings AS generation_settings FROM chronicle_messages m "
                "LEFT JOIN chronicle_generations g ON g.chronicle_id=m.chronicle_id AND g.request_id=m.request_id "
                "WHERE m.chronicle_id=? ORDER BY m.sequence", (chronicle_id,))]

    @staticmethod
    def message(row) -> dict:
        value = {"id": row["id"], "role": row["role"], "text": row["text"],
                 "thinking": row["thinking"], "created_at": row["created_at"], "status": row["status"]}
        if row["status"] == "streaming" and row["request_id"]:
            value["request_id"] = row["request_id"]
            if "generation_settings" in row.keys() and row["generation_settings"]:
                value["streaming_speed"] = json.loads(row["generation_settings"])["streaming_speed"]
        return value

    def settings(self) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT data FROM chronicle_preferences WHERE id='shared'").fetchone()
        if row is None:
            return json.loads(json.dumps(DEFAULT_SETTINGS))
        value = {**DEFAULT_SETTINGS, **json.loads(row["data"])}
        value["sections"] = {**DEFAULT_SETTINGS["sections"], **value.get("sections", {})}
        return value

    def save_settings(self, value: dict) -> dict:
        normalized = {**DEFAULT_SETTINGS, **value,
                      "sections": {**DEFAULT_SETTINGS["sections"], **value["sections"]}}
        with self.connect() as db:
            db.execute("INSERT INTO chronicle_preferences(id,data) VALUES('shared',?) "
                       "ON CONFLICT(id) DO UPDATE SET data=excluded.data", (json.dumps(normalized),))
        return normalized

    def begin_generation(self, chronicle_id: str, request_id: str, text: str, settings: dict):
        fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            chronicle = self.require(chronicle_id, db=db)
            prior = db.execute("SELECT * FROM chronicle_generations WHERE chronicle_id=? AND request_id=?",
                               (chronicle_id, request_id)).fetchone()
            if prior:
                if prior["fingerprint"] != fingerprint:
                    raise CreationConflict("This request ID was already used for a different message.")
                return {"new": False, "generation": dict(prior),
                        "user_message": self._message_in(db, prior["user_message_id"])}
            active = db.execute("SELECT request_id FROM chronicle_generations WHERE chronicle_id=? AND status='running' LIMIT 1",
                                (chronicle_id,)).fetchone()
            if active:
                raise CreationConflict("A response is already being generated in this Chronicle.")
            seq = db.execute("SELECT COALESCE(MAX(sequence),0) FROM chronicle_messages WHERE chronicle_id=?",
                             (chronicle_id,)).fetchone()[0]
            created = timestamp()
            user_id, answer_id = str(uuid4()), str(uuid4())
            db.execute("INSERT INTO chronicle_messages VALUES(?,?,?,?,?,?,?,?,?)",
                       (user_id, chronicle_id, seq + 1, "user", text, "", "complete", created, request_id))
            db.execute("INSERT INTO chronicle_messages VALUES(?,?,?,?,?,?,?,?,?)",
                       (answer_id, chronicle_id, seq + 2, "assistant", "", "", "streaming", created, request_id))
            db.execute("UPDATE chronicles SET last_message_at=? WHERE id=?", (created, chronicle_id))
            db.execute("INSERT INTO chronicle_generations VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (chronicle_id, request_id, fingerprint, "running", user_id, answer_id,
                        json.dumps(settings), None, created, created))
            generation = dict(db.execute("SELECT * FROM chronicle_generations WHERE chronicle_id=? AND request_id=?",
                                         (chronicle_id, request_id)).fetchone())
            return {"new": True, "generation": generation, "user_message": self._message_in(db, user_id)}

    def _message_in(self, db, message_id: str) -> dict:
        row = db.execute("SELECT m.*,g.settings AS generation_settings FROM chronicle_messages m "
                         "LEFT JOIN chronicle_generations g ON g.chronicle_id=m.chronicle_id "
                         "AND g.request_id=m.request_id WHERE m.id=?", (message_id,)).fetchone()
        return self.message(row)

    def generation(self, chronicle_id: str, request_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM chronicle_generations WHERE chronicle_id=? AND request_id=?",
                             (chronicle_id, request_id)).fetchone()
            return dict(row) if row else None

    def existing_request(self, chronicle_id: str, request_id: str, text: str):
        fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()
        with self.connect() as db:
            chronicle = db.execute("SELECT id FROM chronicles WHERE id=?", (chronicle_id,)).fetchone()
            if chronicle is None:
                raise KeyError(chronicle_id)
            row = db.execute("SELECT * FROM chronicle_generations WHERE chronicle_id=? AND request_id=?",
                             (chronicle_id, request_id)).fetchone()
            if row is None:
                return None
            if row["fingerprint"] != fingerprint:
                raise CreationConflict("This request ID was already used for a different message.")
            return {"new": False, "generation": dict(row),
                    "user_message": self._message_in(db, row["user_message_id"])}

    def generation_messages(self, generation: dict) -> tuple[dict, dict | None] | None:
        with self.connect() as db:
            user = db.execute("SELECT * FROM chronicle_messages WHERE id=?", (generation["user_message_id"],)).fetchone()
            answer = db.execute("SELECT m.*,g.settings AS generation_settings FROM chronicle_messages m "
                                "LEFT JOIN chronicle_generations g ON g.chronicle_id=m.chronicle_id "
                                "AND g.request_id=m.request_id WHERE m.id=?",
                                (generation["assistant_message_id"],)).fetchone()
            if user is None:
                return None
            return self.message(user), self.message(answer) if answer is not None else None

    def append(self, chronicle_id: str, request_id: str, field: str, text: str):
        column = "thinking" if field == "thinking" else "text"
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            generation = db.execute("SELECT assistant_message_id,status FROM chronicle_generations "
                                    "WHERE chronicle_id=? AND request_id=?", (chronicle_id, request_id)).fetchone()
            if not generation or generation["status"] != "running":
                return
            db.execute(f"UPDATE chronicle_messages SET {column}={column} || ? WHERE id=?",
                       (text, generation["assistant_message_id"]))
            current = timestamp()
            db.execute("UPDATE chronicle_generations SET updated_at=? WHERE chronicle_id=? AND request_id=?",
                       (current, chronicle_id, request_id))
            db.execute("UPDATE chronicles SET last_message_at=? WHERE id=?", (current, chronicle_id))

    def finish(self, chronicle_id: str, request_id: str, state: str, error_code: str | None = None):
        message_status = {"completed": "complete", "stopped": "stopped", "failed": "error"}[state]
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            generation = db.execute("SELECT * FROM chronicle_generations WHERE chronicle_id=? AND request_id=?",
                                    (chronicle_id, request_id)).fetchone()
            if not generation or generation["status"] != "running":
                return None
            text = db.execute("SELECT text,thinking FROM chronicle_messages WHERE id=?",
                              (generation["assistant_message_id"],)).fetchone()
            has_content = bool(text and (text["text"] or text["thinking"]))
            if has_content and state == "failed":
                message_status = "partial"
            if has_content:
                db.execute("UPDATE chronicle_messages SET status=?,created_at=? WHERE id=?",
                           (message_status, timestamp(), generation["assistant_message_id"]))
            else:
                db.execute("DELETE FROM chronicle_messages WHERE id=?", (generation["assistant_message_id"],))
            db.execute("UPDATE chronicle_generations SET status=?,error_code=?,updated_at=? "
                       "WHERE chronicle_id=? AND request_id=?",
                       (state, error_code, timestamp(), chronicle_id, request_id))
            db.execute("UPDATE chronicles SET last_message_at=? WHERE id=?", (timestamp(), chronicle_id))
        latest = self.generation(chronicle_id, request_id)
        pair = self.generation_messages(latest)
        return pair[1] if pair else None

    def stop_or_recover_running(self):
        """Close an interrupted stream as a durable partial result after an app restart."""
        with self.connect() as db:
            rows = db.execute("SELECT chronicle_id,request_id FROM chronicle_generations WHERE status='running'").fetchall()
        for row in rows:
            self.finish(row["chronicle_id"], row["request_id"], "failed", "interrupted")


class ChronicleService:
    def __init__(self, creation, *, chat_client=None):
        self.creation = creation
        self.store = ChronicleStore(creation.store.path)
        self.worlds = creation.worlds
        self.vault = creation.vault
        self.embedder = creation.embedder
        self.logger = creation.logger
        self.chat_client = chat_client
        self.guard = threading.RLock()
        self.stops: dict[tuple[str, str], threading.Event] = {}
        self.threads: dict[tuple[str, str], threading.Thread] = {}
        self.responses: dict[tuple[str, str], httpx.Response] = {}

    def start_service(self, logger):
        self.logger = logger
        self.store.stop_or_recover_running()

    def close(self):
        with self.guard:
            stops = list(self.stops.values())
            threads = list(self.threads.values())
            responses = list(self.responses.values())
            for stop in stops:
                stop.set()
            for response in responses:
                response.close()
        for thread in threads:
            thread.join(timeout=5)

    def require_world_or_attempt(self, world_id: str):
        try:
            return self.worlds.get(world_id)
        except FileNotFoundError:
            attempt = self.creation.store.get(world_id)
            if attempt is not None:
                return {"id": world_id, "name": attempt.get("name", ""), "processing": True}
            raise KeyError(world_id) from None

    def list_chronicles(self, world_id: str) -> list[dict]:
        self.require_world_or_attempt(world_id)
        return self.store.list(world_id)

    def world_activity(self) -> dict[str, str]:
        return self.store.world_activity()

    def create_chronicle(self, world_id: str) -> dict:
        self.require_world_or_attempt(world_id)
        value = self.store.create(world_id)
        self.logger.info("Chronicle created world_id=%s chronicle_id=%s", world_id, value["id"])
        return value

    def chronicle(self, chronicle_id: str) -> dict:
        try:
            return self.store.require(chronicle_id)
        except KeyError:
            raise KeyError(chronicle_id) from None

    def messages(self, chronicle_id: str) -> list[dict]:
        self.chronicle(chronicle_id)
        return self.store.messages(chronicle_id)

    def delete_chronicle(self, chronicle_id: str):
        self.chronicle(chronicle_id)
        with self.guard:
            for key, stop in list(self.stops.items()):
                if key[0] != chronicle_id:
                    continue
                stop.set()
                response = self.responses.get(key)
                if response:
                    response.close()
            if not self.store.delete(chronicle_id):
                raise KeyError(chronicle_id)
        self.logger.info("Chronicle deleted chronicle_id=%s", chronicle_id)

    def _require_embedded_world(self, world_id: str):
        try:
            self.worlds.get(world_id)
            books = self.worlds.books(world_id)
        except FileNotFoundError:
            raise CreationConflict("Chat is available after this World finishes processing its books.") from None
        if not books:
            raise CreationConflict("Chat is available after this World finishes processing its books.")
        with self.creation.store.connect() as db:
            for book in books:
                counts = db.execute("SELECT COUNT(*) total, COUNT(vector) complete FROM chunks "
                                    "WHERE world_id=? AND book_id=?", (world_id, book["id"])).fetchone()
                if counts["total"] == 0 or counts["total"] != counts["complete"]:
                    raise CreationConflict("Chat is available after this World finishes processing its books.")
        return books

    def _snapshot(self) -> tuple[dict, str]:
        settings = self.store.settings()
        if settings["model"] not in CHAT_MODEL_IDS:
            raise CreationConflict("Choose a supported chat model in Chronicle settings.")
        key_id = settings["key_id"]
        if not key_id:
            raise CreationConflict("Choose an API key in Chronicle settings before sending a message.")
        if not self.creation.store.enabled_key(key_id):
            raise CreationConflict("The selected API key is unavailable. Choose an enabled key in Chronicle settings.")
        secret = self.vault.read(key_id)
        if not secret:
            raise CreationConflict("The selected API key secret is missing. Choose another key in Chronicle settings.")
        return settings, secret

    def start_generation(self, chronicle_id: str, request_id: str, text: str):
        with self.guard:
            chronicle = self.chronicle(chronicle_id)
            existing = self.store.existing_request(chronicle_id, request_id, text)
            if existing is not None:
                return existing
            self._require_embedded_world(chronicle["world_id"])
            settings, secret = self._snapshot()
            result = self.store.begin_generation(chronicle_id, request_id, text, settings)
            key = (chronicle_id, request_id)
            if result["new"]:
                self._record_world_activity(chronicle["world_id"], result["user_message"]["created_at"])
                stop = threading.Event()
                thread = threading.Thread(target=self._run_generation,
                                          args=(chronicle_id, request_id, text, settings, secret, stop),
                                          name=f"chronicle-{chronicle_id[:8]}", daemon=True)
                self.stops[key] = stop
                self.threads[key] = thread
                thread.start()
            return result

    def stop_generation(self, chronicle_id: str, request_id: str) -> dict:
        key = (chronicle_id, request_id)
        thread = None
        with self.guard:
            generation = self.store.generation(chronicle_id, request_id)
            if generation is None:
                raise KeyError(request_id)
            if generation["status"] not in TERMINAL_GENERATION_STATES:
                stop = self.stops.get(key)
                if stop:
                    stop.set()
                response = self.responses.get(key)
                if response:
                    response.close()
                thread = self.threads.get(key)
        if thread and thread is not threading.current_thread():
            thread.join(timeout=5)
        generation = self.store.generation(chronicle_id, request_id)
        pair = self.store.generation_messages(generation) if generation else None
        status = generation["status"] if generation else "missing"
        return {"stopped": status == "stopped", "status": "stopping" if status == "running" else status,
                "message": pair[1] if pair else None}

    def stream_events(self, chronicle_id: str, request_id: str, user_message: dict):
        yield self._sse("user_message", {"message": user_message})
        thinking_offset = answer_offset = 0
        while True:
            generation = self.store.generation(chronicle_id, request_id)
            if generation is None:
                yield self._sse("error", {"code": "missing_generation", "message": "The response could not be loaded."})
                return
            pair = self.store.generation_messages(generation)
            if pair is None:
                yield self._sse("error", {"code": "missing_message", "message": "The response could not be loaded."})
                return
            answer = pair[1]
            if answer is None:
                if generation["status"] == "failed":
                    yield self._sse("error", {"code": generation["error_code"] or "generation_failed",
                                              "message": "The model could not finish this response.",
                                              "assistant": None})
                elif generation["status"] in TERMINAL_GENERATION_STATES:
                    yield self._sse("completed", {"message": None})
                else:
                    yield self._sse("error", {"code": "missing_message", "message": "The response could not be loaded."})
                return
            if len(answer["thinking"]) > thinking_offset:
                delta = answer["thinking"][thinking_offset:]
                thinking_offset = len(answer["thinking"])
                yield self._sse("thinking_delta", {"text": delta})
            if len(answer["text"]) > answer_offset:
                delta = answer["text"][answer_offset:]
                answer_offset = len(answer["text"])
                yield self._sse("answer_delta", {"text": delta})
            if generation["status"] in TERMINAL_GENERATION_STATES:
                if generation["status"] == "failed":
                    yield self._sse("error", {"code": generation["error_code"] or "generation_failed",
                                              "message": "The model could not finish this response.",
                                              "assistant": answer})
                else:
                    yield self._sse("completed", {"message": answer})
                return
            time.sleep(0.05)

    @staticmethod
    def _sse(event: str, value: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(value, ensure_ascii=False)}\n\n"

    def _run_generation(self, chronicle_id, request_id, latest_text, settings, secret, stop):
        state, code = "completed", None
        key = (chronicle_id, request_id)
        try:
            query = self._embed_query(latest_text, secret, stop)
            if stop.is_set():
                raise ProcessingPaused()
            chronicle = self.store.require(chronicle_id)
            chunks = self._retrieve(chronicle["world_id"], query, settings)
            prompt = self._prompt(chronicle_id, request_id, latest_text, chunks, settings)
            for kind, delta in self._provider_deltas(settings["model"], prompt, secret, key, stop):
                if stop.is_set():
                    raise ProcessingPaused()
                if delta:
                    self.store.append(chronicle_id, request_id, kind, delta)
            if stop.is_set():
                state = "stopped"
        except ProcessingPaused:
            state = "stopped"
        except EmbeddingFailure as exc:
            state, code = "failed", exc.code
        except Exception as exc:
            state, code = "failed", "provider_unavailable"
            self.logger.error("Chronicle generation failed chronicle_id=%s request_id=%s type=%s",
                              chronicle_id, request_id, type(exc).__name__)
        finally:
            self.store.finish(chronicle_id, request_id, state, code)
            chronicle = self.store.require(chronicle_id)
            self._record_world_activity(chronicle["world_id"], chronicle["last_message_at"])
            if state == "completed":
                self.logger.info("Chronicle response completed chronicle_id=%s request_id=%s",
                                 chronicle_id, request_id)
            elif state == "stopped":
                self.logger.info("Chronicle response stopped chronicle_id=%s request_id=%s",
                                 chronicle_id, request_id)
            with self.guard:
                self.stops.pop(key, None)
                self.threads.pop(key, None)
                self.responses.pop(key, None)

    def _record_world_activity(self, world_id: str, at: str | None):
        try:
            self.worlds.record_activity(world_id, at)
        except (OSError, Timeout, json.JSONDecodeError):
            self.logger.warning("World activity timestamp could not be saved world_id=%s", world_id)

    def _embed_query(self, text: str, secret: str, stop: threading.Event) -> list[float]:
        if hasattr(self.embedder, "embed_query"):
            vector = self.embedder.embed_query(text, secret, stop, self.logger)
        else:
            # Test and extension embedders that implement the original protocol still work.
            vector = self.embedder.embed(f"task: search result | query: {text}", secret, stop, self.logger)
        return self._normalize(vector)

    @staticmethod
    def _normalize(vector) -> list[float]:
        values = list(vector)
        if not values or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
            raise EmbeddingFailure("invalid_vector", "The query embedding was invalid. Retry this message.")
        norm = math.sqrt(sum(float(v) * float(v) for v in values))
        if norm == 0:
            raise EmbeddingFailure("invalid_vector", "The query embedding was invalid. Retry this message.")
        return [float(v) / norm for v in values]

    def _retrieve(self, world_id: str, query: list[float], settings: dict) -> list[dict]:
        with self.creation.store.connect() as db:
            rows = [dict(row) for row in db.execute(
                "SELECT * FROM chunks WHERE world_id=? AND vector IS NOT NULL", (world_id,))]
        if not rows:
            return []
        by_book: dict[str, list[dict]] = {}
        scored = []
        for row in rows:
            if row["dimensions"] != len(query) or len(row["vector"]) != 4 * len(query):
                continue
            vector = struct.unpack(f"<{len(query)}f", row["vector"])
            norm = math.sqrt(sum(value * value for value in vector))
            if not norm:
                continue
            by_book.setdefault(row["book_id"], []).append(row)
            similarity = sum(left * right for left, right in zip(query, vector)) / norm
            if similarity >= settings["minimum_similarity"]:
                row["similarity"] = similarity
                scored.append(row)
        scored.sort(key=lambda row: (-row["similarity"], row["book_id"], row["start"], row["id"]))
        selected = scored[:settings["chunk_count"]]
        books = {book["id"]: book for book in self.worlds.books(world_id)}
        passages = []
        for row in selected:
            before = ""
            cursor = row["start"]
            remaining = settings["chunk_overlap"]
            previous = sorted((chunk for chunk in by_book[row["book_id"]]
                               if chunk["end"] <= cursor), key=lambda chunk: chunk["start"], reverse=True)
            pieces = []
            for chunk in previous:
                if chunk["end"] != cursor:
                    break
                take = min(remaining, len(chunk["text"]))
                pieces.insert(0, chunk["text"][-take:] if take else "")
                remaining -= take
                cursor = chunk["start"]
                if remaining == 0:
                    break
            before = "".join(pieces)
            book = books.get(row["book_id"], {"filename": "Unknown book"})
            passages.append({
                "text": row["text"],
                "filename": book["filename"],
                "start": max(0, row["start"] - len(before)),
                "end": row["end"],
                "similarity": row["similarity"],
                "context": before,
            })
        return passages

    def _prompt(self, chronicle_id: str, request_id: str, latest_text: str,
                chunks: list[dict], settings: dict) -> str:
        with self.store.connect() as db:
            messages = [dict(row) for row in db.execute(
                "SELECT * FROM chronicle_messages WHERE chronicle_id=? ORDER BY sequence", (chronicle_id,))]
        history = []
        for message in messages:
            if message["request_id"] == request_id:
                continue
            if message["role"] == "user":
                history.append(f"User: {message['text']}")
            elif message["text"].strip():
                history.append(f"Assistant: {message['text']}")
        history_section = (settings["chat_history_prefix"] + "\n" + "\n\n".join(history) + "\n" +
                           settings["chat_history_suffix"])
        retrieved = "\n\n".join(
            f"[{item['filename']} | chars {item['start']}-{item['end']}]\n{item['context']}{item['text']}"
            for item in chunks)
        retrieved_section = (settings["rag_chunks_prefix"] + "\n" + retrieved + "\n" +
                             settings["rag_chunks_suffix"])
        return f"{history_section}\n\n{retrieved_section}\n\n{latest_text}"

    def _provider_deltas(self, model: str, prompt: str, secret: str,
                         key: tuple[str, str], stop: threading.Event):
        payload = {"model": model, "input": prompt, "stream": True, "store": False}
        if model != "gemma-4-31b-it":
            payload["generation_config"] = {"thinking_summaries": "auto"}
        owned_client = self.chat_client is None
        client = self.chat_client or httpx.Client(timeout=httpx.Timeout(60, connect=10))
        event_name = None
        data_lines = []
        step_types = {}
        completed = False
        try:
            with client.stream("POST", "https://generativelanguage.googleapis.com/v1beta/interactions",
                               headers={"x-goog-api-key": secret, "Content-Type": "application/json"},
                               json=payload) as response:
                with self.guard:
                    self.responses[key] = response
                if response.status_code >= 400:
                    body = response.read()
                    if response.status_code in (401, 403):
                        raise EmbeddingFailure("credentials", "Google rejected this API key. Check Providers in Settings.")
                    if response.status_code == 429 or response.status_code >= 500:
                        raise EmbeddingFailure("provider_unavailable", "Google is unavailable or its usage limit was reached.")
                    raise EmbeddingFailure("provider_request", "Google could not process this message. Check the model and key.")
                for line in response.iter_lines():
                    if stop.is_set():
                        break
                    if line == "":
                        item = self._provider_event(event_name, "\n".join(data_lines))
                        event_name, data_lines = None, []
                        if item is None:
                            continue
                        kind, value = item
                        if kind == "step_start":
                            step_types[value["index"]] = value["type"]
                            initial_text = value.get("summary", []) if value["type"] == "thought" else value.get("content", [])
                            for content in initial_text:
                                if content.get("type") == "text" and content.get("text"):
                                    yield ("thinking" if value["type"] == "thought" else "answer"), content["text"]
                        elif kind == "delta":
                            delta_type, text, index = value
                            if delta_type == "thought_summary" or step_types.get(index) == "thought":
                                yield "thinking", text
                            elif delta_type == "text":
                                yield "answer", text
                        elif kind == "failed":
                            raise EmbeddingFailure("provider_request", "Google could not finish this message.")
                        elif kind == "completed":
                            if value.get("status") != "completed":
                                raise EmbeddingFailure("provider_request", "Google did not complete this message.")
                            completed = True
                        continue
                    if line.startswith("event:"):
                        event_name = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                if data_lines:
                    item = self._provider_event(event_name, "\n".join(data_lines))
                    if item:
                        kind, value = item
                        if kind == "step_start":
                            step_types[value["index"]] = value["type"]
                            initial_text = value.get("summary", []) if value["type"] == "thought" else value.get("content", [])
                            for content in initial_text:
                                if content.get("type") == "text" and content.get("text"):
                                    yield ("thinking" if value["type"] == "thought" else "answer"), content["text"]
                        elif kind == "delta":
                            delta_type, text, index = value
                            if delta_type == "thought_summary" or step_types.get(index) == "thought":
                                yield "thinking", text
                            elif delta_type == "text":
                                yield "answer", text
                        elif kind == "failed":
                            raise EmbeddingFailure("provider_request", "Google could not finish this message.")
                        elif kind == "completed":
                            if value.get("status") != "completed":
                                raise EmbeddingFailure("provider_request", "Google did not complete this message.")
                            completed = True
                if not completed and not stop.is_set():
                    raise EmbeddingFailure("provider_incomplete", "Google ended this message before completing it.")
        except (httpx.HTTPError, RuntimeError) as exc:
            if not stop.is_set():
                raise EmbeddingFailure("provider_unavailable", "Google is unavailable or its usage limit was reached.") from exc
        finally:
            with self.guard:
                self.responses.pop(key, None)
            if owned_client:
                client.close()

    @staticmethod
    def _provider_event(event_name: str | None, raw: str):
        if not raw or raw == "[DONE]":
            return None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return None
        kind = value.get("event_type", event_name)
        if kind == "step.start":
            step = value.get("step") or {}
            content = step.get("content", [])
            if isinstance(content, dict):
                content = [content]
            summary = step.get("summary", [])
            if isinstance(summary, dict):
                summary = [summary]
            return "step_start", {"index": value.get("index", -1), "type": step.get("type"),
                                   "content": content if isinstance(content, list) else [],
                                   "summary": summary if isinstance(summary, list) else []}
        if kind == "step.delta":
            delta = value.get("delta") or {}
            delta_type = delta.get("type")
            if delta_type == "thought_summary":
                content = delta.get("content") or {}
                return "delta", (delta_type, content.get("text", ""), value.get("index", -1))
            if delta_type == "text":
                return "delta", ("text", delta.get("text", ""), value.get("index", -1))
        if kind == "interaction.completed":
            interaction = value.get("interaction") or {}
            return "completed", {"status": interaction.get("status", "completed")}
        if kind == "interaction.status_update" and value.get("status") in {"failed", "cancelled", "incomplete"}:
            return "failed", value.get("status")
        if kind in {"interaction.failed", "interaction.error"}:
            return "failed", value.get("error")
        if kind == "error":
            return "failed", value
        return None
