"""Transactional creation checkpoints and world-scoped chunks and embeddings."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
from uuid import uuid5, NAMESPACE_URL

from .books.chunking import CHUNKER_VERSION, TextChunk
from .embeddings import MODEL, DIMENSIONS, INPUT_FORMAT_VERSION


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CreationConflict(Exception):
    pass


class CreationStore:
    def __init__(self, root: Path):
        self.root = root
        self.path = root / "processing.sqlite3"
        if self.path.is_symlink():
            raise OSError("Invalid processing storage.")
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS chunks(
                    id TEXT PRIMARY KEY, world_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
                    book_id TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL,
                    text TEXT NOT NULL, digest TEXT NOT NULL, config TEXT NOT NULL,
                    vector BLOB, model TEXT, dimensions INTEGER,
                    UNIQUE(world_id, book_id, start));
                CREATE TABLE IF NOT EXISTS provider_keys(id TEXT PRIMARY KEY, name TEXT NOT NULL, provider TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS preferences(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS commands(
                    id TEXT PRIMARY KEY, world_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
                    fingerprint TEXT NOT NULL);
            """)
            if "position" not in {row[1] for row in db.execute("PRAGMA table_info(chunks)")}:
                db.execute("ALTER TABLE chunks ADD COLUMN position INTEGER")

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

    def get(self, attempt_id: str | None = None, *, db=None) -> dict | None:
        if db is None:
            with self.connect() as connection:
                return self.get(attempt_id, db=connection)
        rows = db.execute("SELECT data FROM attempts" + (" WHERE id=?" if attempt_id else ""),
                          (attempt_id,) if attempt_id else ()).fetchall()
        for row in rows:
            value = json.loads(row["data"])
            if attempt_id or value["state"] != "complete":
                return value
        return None

    def put(self, db, value: dict):
        value["updated_at"] = now()
        db.execute("INSERT INTO attempts VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                   (value["id"], json.dumps(value)))

    def update(self, attempt_id: str, **changes):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            value = self.get(attempt_id, db=db)
            value.update(changes)
            self.put(db, value)

    def update_book(self, attempt_id: str, book_id: str, **changes):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            value = self.get(attempt_id, db=db)
            book = next(b for b in value["books"] if b["id"] == book_id)
            book.update(changes)
            self.put(db, value)

    def public(self, value: dict | None) -> dict | None:
        if value is None:
            return None
        result = {key: val for key, val in value.items() if key != "last_manifest"}
        with self.connect() as db:
            books = []
            for book in result["books"]:
                counts = db.execute("SELECT COUNT(*) total, COUNT(vector) done FROM chunks WHERE world_id=? AND book_id=?",
                                    (value["id"], book["id"])).fetchone()
                books.append({**{key: val for key, val in book.items() if key not in ("digest", "upload_id")},
                              "chunks_total": counts["total"], "chunks_done": counts["done"]})
            result["books"] = books
        result["chunks_total"] = sum(b["chunks_total"] for b in books)
        result["chunks_done"] = sum(b["chunks_done"] for b in books)
        result["books_done"] = sum(b["state"] == "done" for b in books)
        return result

    def keys(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM provider_keys ORDER BY name,id")]

    def defaults(self) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT data FROM preferences WHERE id='processing'").fetchone()
            return json.loads(row[0]) if row else {"model": MODEL, "key_id": ""}

    def add_chunks(self, attempt_id: str, book_id: str, chunks: list[TextChunk], config: dict, *, replace_id=None):
        profile = json.dumps({**config, "chunker_version": CHUNKER_VERSION,
                              "input_format_version": INPUT_FORMAT_VERSION, "dimensions": DIMENSIONS}, sort_keys=True)
        with self.connect() as db:
            if replace_id:
                db.execute("DELETE FROM chunks WHERE id=? AND world_id=?", (replace_id, attempt_id))
            for chunk in chunks:
                digest = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
                identity = f"{attempt_id}/{book_id}/{chunk.start}/{chunk.end}/{digest}/{profile}"
                db.execute("INSERT OR IGNORE INTO chunks(id,world_id,book_id,start,end,text,digest,config) VALUES(?,?,?,?,?,?,?,?)",
                           (uuid5(NAMESPACE_URL, identity).hex, attempt_id, book_id, chunk.start, chunk.end,
                            chunk.text, digest, profile))
            ordered = db.execute("SELECT id FROM chunks WHERE world_id=? AND book_id=? ORDER BY start",
                                 (attempt_id, book_id)).fetchall()
            db.executemany("UPDATE chunks SET position=? WHERE id=?", [(position, row[0]) for position, row in enumerate(ordered, 1)])

    def pending_chunk(self, attempt_id: str, book_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM chunks WHERE world_id=? AND book_id=? AND vector IS NULL ORDER BY start LIMIT 1",
                             (attempt_id, book_id)).fetchone()
            return dict(row) if row else None

    def save_vector(self, chunk_id: str, values: list[float]):
        with self.connect() as db:
            db.execute("UPDATE chunks SET vector=?,model=?,dimensions=? WHERE id=?",
                       (struct.pack(f"<{DIMENSIONS}f", *values), MODEL, DIMENSIONS, chunk_id))

    def command(self, db, attempt_id: str, command_id: str, payload: dict) -> bool:
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        prior = db.execute("SELECT * FROM commands WHERE id=?", (command_id,)).fetchone()
        if prior:
            if prior["world_id"] != attempt_id or prior["fingerprint"] != fingerprint:
                raise CreationConflict("This operation ID was already used for a different request.")
            return False
        db.execute("INSERT INTO commands VALUES(?,?,?)", (command_id, attempt_id, fingerprint))
        return True
