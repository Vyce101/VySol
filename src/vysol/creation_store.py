"""Transactional creation checkpoints and world-scoped chunks and embeddings."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
from uuid import uuid4, uuid5, NAMESPACE_URL

from .books.chunking import CHUNKER_VERSION, TextChunk
from .embeddings import MODEL, DIMENSIONS, INPUT_FORMAT_VERSION


PROVIDER_IDS = ("google", "openai", "anthropic", "deepseek", "openai_compatible")
MODEL_CATALOG_MAX_AGE_SECONDS = 24 * 60 * 60


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
                CREATE TABLE IF NOT EXISTS provider_model_catalog(
                    key_id TEXT PRIMARY KEY REFERENCES provider_keys(id) ON DELETE CASCADE,
                    models TEXT NOT NULL DEFAULT '[]', refreshed_at TEXT,
                    attempted_at TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS provider_connections(
                    id TEXT PRIMARY KEY, provider TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS provider_sequences(
                    provider TEXT PRIMARY KEY, next_sequence INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS preferences(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS commands(
                    id TEXT PRIMARY KEY, world_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
                    fingerprint TEXT NOT NULL);
            """)
            if "position" not in {row[1] for row in db.execute("PRAGMA table_info(chunks)")}:
                db.execute("ALTER TABLE chunks ADD COLUMN position INTEGER")
            key_columns = {row[1] for row in db.execute("PRAGMA table_info(provider_keys)")}
            if "connection_id" not in key_columns:
                db.execute("ALTER TABLE provider_keys ADD COLUMN connection_id TEXT")
            if "sequence" not in key_columns:
                db.execute("ALTER TABLE provider_keys ADD COLUMN sequence INTEGER")
            if "base_url" not in key_columns:
                db.execute("ALTER TABLE provider_keys ADD COLUMN base_url TEXT")
            connection_columns = {row[1] for row in db.execute("PRAGMA table_info(provider_connections)")}
            if "enabled" not in connection_columns:
                db.execute("ALTER TABLE provider_connections ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
        self._migrate_provider_connections()

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
        if attempt_id is None:
            attempts = self.pending(db=db)
            return attempts[0] if attempts else None
        rows = db.execute("SELECT data FROM attempts" + (" WHERE id=?" if attempt_id else ""),
                          (attempt_id,) if attempt_id else ()).fetchall()
        for row in rows:
            value = json.loads(row["data"])
            return value
        return None

    def pending(self, *, db=None) -> list[dict]:
        if db is None:
            with self.connect() as connection:
                return self.pending(db=connection)
        attempts = [json.loads(row["data"]) for row in db.execute("SELECT data FROM attempts")]
        return sorted((attempt for attempt in attempts if attempt["state"] != "complete"),
                      key=lambda attempt: (attempt.get("updated_at", ""), attempt["id"]), reverse=True)

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
            rows = [dict(row) for row in db.execute(
                "SELECT k.id,k.name,k.provider,k.connection_id,k.sequence,k.base_url,c.enabled "
                "FROM provider_keys k LEFT JOIN provider_connections c ON c.id=k.connection_id "
                "ORDER BY k.provider,k.name COLLATE NOCASE,k.id")]
            catalogs = {row["key_id"]: row for row in db.execute(
                "SELECT key_id,models,refreshed_at,error FROM provider_model_catalog")}
        for credential in rows:
            credential["enabled"] = bool(credential["enabled"])
            credential.update(self._public_catalog(catalogs.get(credential["id"])))
        return rows

    def connections(self) -> list[dict]:
        with self.connect() as db:
            connections = [dict(row) for row in db.execute(
                "SELECT id,provider,created_at,enabled FROM provider_connections ORDER BY provider COLLATE NOCASE,id")]
            for connection in connections:
                connection["enabled"] = bool(connection["enabled"])
                connection["next_sequence"] = self._peek_next_sequence(db, connection["id"])
            credentials = db.execute(
                "SELECT id,name,provider,connection_id,sequence,base_url FROM provider_keys "
                "ORDER BY provider,name COLLATE NOCASE,id"
            ).fetchall()
            catalogs = {row["key_id"]: row for row in db.execute(
                "SELECT key_id,models,refreshed_at,error FROM provider_model_catalog")}
        credentials_by_connection = {connection["id"]: [] for connection in connections}
        for row in credentials:
            credential = dict(row)
            credential.update(self._public_catalog(catalogs.get(credential["id"])))
            connection_id = credential["connection_id"]
            if connection_id in credentials_by_connection:
                credentials_by_connection[connection_id].append(credential)
        for connection in connections:
            connection["credentials"] = credentials_by_connection[connection["id"]]
        return connections

    def add_connection(self, provider: str) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            connection = self._get_or_create_connection(db, provider)
            connection["enabled"] = bool(connection["enabled"])
            connection["next_sequence"] = self._peek_next_sequence(db, connection["id"])
            connection["credentials"] = []
            return connection

    def update_connection(self, connection_id: str, enabled: bool) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id,provider,created_at,enabled FROM provider_connections WHERE id=?",
                             (connection_id,)).fetchone()
            if row is None:
                raise KeyError(connection_id)
            db.execute("UPDATE provider_connections SET enabled=? WHERE id=?", (int(enabled), connection_id))
            value = dict(row)
            value["enabled"] = bool(enabled)
            value["next_sequence"] = self._peek_next_sequence(db, connection_id)
            value["credentials"] = [dict(credential) for credential in db.execute(
                "SELECT id,name,provider,connection_id,sequence,base_url FROM provider_keys WHERE connection_id=? "
                "ORDER BY provider,name COLLATE NOCASE,id", (connection_id,))]
            for credential in value["credentials"]:
                cache = db.execute(
                    "SELECT models,refreshed_at,error FROM provider_model_catalog WHERE key_id=?",
                    (credential["id"],),
                ).fetchone()
                credential.update(self._public_catalog(cache))
            return value

    def enabled_key(self, key_id: str, *, db=None) -> bool:
        if db is None:
            with self.connect() as connection:
                return self.enabled_key(key_id, db=connection)
        row = db.execute(
            "SELECT c.enabled FROM provider_keys k JOIN provider_connections c ON c.id=k.connection_id WHERE k.id=?",
            (key_id,),
        ).fetchone()
        return bool(row and row["enabled"])

    def save_key(self, db, key_id: str, name: str, provider: str, connection_id: str | None,
                 base_url: str | None = None) -> dict:
        connection = self._get_or_create_connection(db, provider)
        if connection_id is not None and connection_id != connection["id"]:
            raise ValueError("The selected provider connection does not match this credential.")
        existing = db.execute("SELECT sequence FROM provider_keys WHERE id=?", (key_id,)).fetchone()
        sequence = existing["sequence"] if existing else self._allocate_sequence(db, connection["id"])
        db.execute(
            "INSERT INTO provider_keys(id,name,provider,connection_id,sequence,base_url) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name,provider=excluded.provider,"
            "connection_id=excluded.connection_id,sequence=excluded.sequence,base_url=excluded.base_url",
            (key_id, name, provider, connection["id"], sequence, base_url),
        )
        return {"id": key_id, "name": name, "provider": provider,
                "connection_id": connection["id"], "sequence": sequence, "base_url": base_url}

    def _migrate_provider_connections(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT rowid,id,provider,connection_id,sequence FROM provider_keys ORDER BY rowid"
            ).fetchall()
            providers = set(PROVIDER_IDS) | {row["provider"] for row in rows}
            for provider in providers:
                self._get_or_create_connection(db, provider)
            for row in rows:
                connection = self._get_or_create_connection(db, row["provider"])
                connection_id = row["connection_id"]
                if connection_id != connection["id"]:
                    connection_id = connection["id"]
                sequence = row["sequence"]
                if sequence is None:
                    sequence = self._allocate_sequence(db, connection["id"])
                db.execute("UPDATE provider_keys SET connection_id=?,sequence=? WHERE id=?",
                           (connection_id, sequence, row["id"]))
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS provider_keys_sequence ON provider_keys(provider,sequence)")

    @staticmethod
    def _get_or_create_connection(db, provider: str) -> dict:
        row = db.execute("SELECT id,provider,created_at,enabled FROM provider_connections WHERE provider=?",
                         (provider,)).fetchone()
        if row:
            connection = dict(row)
            connection["enabled"] = bool(connection["enabled"])
            return connection
        connection = {"id": str(uuid4()), "provider": provider, "created_at": now(), "enabled": 1}
        db.execute("INSERT INTO provider_connections(id,provider,created_at,enabled) VALUES(?,?,?,?)",
                   (connection["id"], provider, connection["created_at"], connection["enabled"]))
        connection["enabled"] = True
        return connection

    @staticmethod
    def _public_catalog(row) -> dict:
        if row is None:
            return {"models": [], "models_updated_at": None, "models_error": None}
        return {
            "models": json.loads(row["models"]),
            "models_updated_at": row["refreshed_at"],
            "models_error": row["error"],
        }

    def credential(self, key_id: str, *, db=None) -> dict | None:
        if db is None:
            with self.connect() as connection:
                return self.credential(key_id, db=connection)
        row = db.execute(
            "SELECT k.id,k.name,k.provider,k.connection_id,k.sequence,k.base_url,c.enabled "
            "FROM provider_keys k LEFT JOIN provider_connections c ON c.id=k.connection_id WHERE k.id=?",
            (key_id,),
        ).fetchone()
        if row is None:
            return None
        value = dict(row)
        value["enabled"] = bool(value["enabled"])
        return value

    def catalog(self, key_id: str, *, db=None) -> dict:
        if db is None:
            with self.connect() as connection:
                return self.catalog(key_id, db=connection)
        row = db.execute(
            "SELECT models,refreshed_at,error FROM provider_model_catalog WHERE key_id=?", (key_id,)
        ).fetchone()
        return self._public_catalog(row)

    def catalog_attempted_at(self, key_id: str) -> str | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT attempted_at FROM provider_model_catalog WHERE key_id=?", (key_id,)
            ).fetchone()
        return row["attempted_at"] if row else None

    def save_catalog(self, key_id: str, models: list[dict]) -> dict:
        refreshed_at = now()
        with self.connect() as db:
            db.execute(
                "INSERT INTO provider_model_catalog(key_id,models,refreshed_at,attempted_at,error) "
                "VALUES(?,?,?,?,NULL) ON CONFLICT(key_id) DO UPDATE SET "
                "models=excluded.models,refreshed_at=excluded.refreshed_at,"
                "attempted_at=excluded.attempted_at,error=NULL",
                (key_id, json.dumps(models), refreshed_at, refreshed_at),
            )
        return {"models": models, "models_updated_at": refreshed_at, "models_error": None}

    def fail_catalog_refresh(self, key_id: str, message: str) -> dict:
        attempted_at = now()
        with self.connect() as db:
            db.execute(
                "INSERT INTO provider_model_catalog(key_id,models,attempted_at,error) VALUES(?, '[]', ?, ?) "
                "ON CONFLICT(key_id) DO UPDATE SET attempted_at=excluded.attempted_at,error=excluded.error",
                (key_id, attempted_at, message),
            )
        return self.catalog(key_id)

    def needs_catalog_refresh(self, key_id: str, max_age_seconds: int = MODEL_CATALOG_MAX_AGE_SECONDS) -> bool:
        with self.connect() as db:
            row = db.execute(
                "SELECT refreshed_at,attempted_at FROM provider_model_catalog WHERE key_id=?", (key_id,)
            ).fetchone()
        if row is None:
            return True
        reference = row["refreshed_at"]
        if reference is None:
            return True
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(reference)
        except (TypeError, ValueError):
            return True
        return age.total_seconds() >= max_age_seconds

    def model_for(self, key_id: str, model_id: str) -> dict | None:
        return next((model for model in self.catalog(key_id)["models"] if model["id"] == model_id), None)

    def credential_used(self, key_id: str) -> bool:
        with self.connect() as db:
            for row in db.execute("SELECT data FROM attempts"):
                try:
                    attempt = json.loads(row["data"])
                    if attempt.get("state") != "complete" and attempt.get("key_id") == key_id:
                        return True
                except (TypeError, json.JSONDecodeError):
                    continue
            tables = {row["name"] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "embedding_profiles" in tables:
                return db.execute(
                    "SELECT 1 FROM embedding_profiles WHERE key_id=? LIMIT 1", (key_id,)
                ).fetchone() is not None
        return False

    def credential_busy(self, key_id: str) -> bool:
        with self.connect() as db:
            tables = {row["name"] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            has_profiles = "embedding_profiles" in tables
            for row in db.execute("SELECT data FROM attempts"):
                try:
                    attempt = json.loads(row["data"])
                except (TypeError, json.JSONDecodeError):
                    continue
                if attempt.get("state") not in {"running", "pausing"}:
                    continue
                if attempt.get("key_id") == key_id:
                    return True
                profile_id = attempt.get("embedding_profile_id")
                if profile_id and has_profiles and db.execute(
                    "SELECT 1 FROM embedding_profiles WHERE id=? AND key_id=? LIMIT 1",
                    (profile_id, key_id),
                ).fetchone():
                    return True
        return False

    @staticmethod
    def _allocate_sequence(db, connection_id: str) -> int:
        occupied = db.execute("SELECT sequence FROM provider_keys WHERE connection_id=? ORDER BY sequence",
                              (connection_id,)).fetchall()
        sequence = 1
        for row in occupied:
            current = row["sequence"]
            if current is None:
                continue
            if current == sequence:
                sequence += 1
            elif current > sequence:
                break
        return sequence

    @staticmethod
    def _peek_next_sequence(db, connection_id: str) -> int:
        return CreationStore._allocate_sequence(db, connection_id)

    def defaults(self) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT data FROM preferences WHERE id='processing'").fetchone()
            return json.loads(row[0]) if row else {"model": MODEL, "key_id": ""}

    def add_chunks(self, attempt_id: str, book_id: str, chunks: list[TextChunk], config: dict, *,
                   replace_id=None, dimensions: int = DIMENSIONS, model: str = MODEL,
                   input_format_version: int = INPUT_FORMAT_VERSION):
        profile = json.dumps({**config, "chunker_version": CHUNKER_VERSION,
                              "input_format_version": input_format_version, "dimensions": dimensions,
                              "model": model}, sort_keys=True)
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

    def save_vector(self, chunk_id: str, values: list[float], *,
                    dimensions: int = DIMENSIONS, model: str = MODEL):
        if len(values) != dimensions:
            raise ValueError("Embedding vector dimensions do not match the world profile.")
        with self.connect() as db:
            db.execute("UPDATE chunks SET vector=?,model=?,dimensions=? WHERE id=?",
                       (struct.pack(f"<{dimensions}f", *values), model, dimensions, chunk_id))

    def command(self, db, attempt_id: str, command_id: str, payload: dict) -> bool:
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        prior = db.execute("SELECT * FROM commands WHERE id=?", (command_id,)).fetchone()
        if prior:
            if prior["world_id"] != attempt_id or prior["fingerprint"] != fingerprint:
                raise CreationConflict("This operation ID was already used for a different request.")
            return False
        db.execute("INSERT INTO commands VALUES(?,?,?)", (command_id, attempt_id, fingerprint))
        return True
