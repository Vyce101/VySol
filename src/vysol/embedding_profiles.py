"""Saved embedding choices and immutable vector specifications for Worlds."""


from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import threading
from uuid import UUID, uuid4

from filelock import FileLock

from .creation_store import CreationConflict
from .embeddings import EmbeddingFailure, ProcessingPaused
from .worlds import atomic_json


LEGACY_MODEL = "gemini-embedding-2"
LEGACY_DIMENSIONS = 768
LEGACY_INPUT_LIMIT = 8192
EMBEDDING_PROVIDERS = {"google", "openai", "openai_compatible"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EmbeddingProfileService:
    def __init__(self, creation, embedder=None):
        self.creation = creation
        self.store = creation.store
        self.root = creation.root
        self.embedder = embedder or creation.embedder
        self.logger = logging.getLogger("vysol.embedding_profiles")
        self._create_schema()
        self._migrate_worlds()

    def _create_schema(self):
        with self.store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS embedding_profiles(
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    key_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    dimensions INTEGER,
                    max_input_tokens INTEGER,
                    preflighted_at TEXT,
                    input_format_version INTEGER NOT NULL DEFAULT 2,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS embedding_profile_state(
                    id TEXT PRIMARY KEY CHECK(id='current'),
                    default_profile_id TEXT,
                    last_used_profile_id TEXT
                );
                INSERT OR IGNORE INTO embedding_profile_state(id,default_profile_id,last_used_profile_id)
                VALUES('current',NULL,NULL);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(embedding_profiles)")}
            if "input_format_version" not in columns:
                db.execute("ALTER TABLE embedding_profiles ADD COLUMN input_format_version INTEGER NOT NULL DEFAULT 2")

    def _migrate_worlds(self):
        folder = self.root / "worlds"
        if not folder.exists():
            return
        for path in folder.glob("*/world.json"):
            world = json.loads(path.read_text(encoding="utf-8"))
            if world.get("embedding_profile_id") or world.get("embedding_spec"):
                continue
            world_id = world.get("id")
            if not world_id:
                continue
            with self.store.connect() as db:
                rows = db.execute(
                    "SELECT DISTINCT model,dimensions FROM chunks WHERE world_id=? AND vector IS NOT NULL",
                    (world_id,),
                ).fetchall()
            specs = {(row["model"] or LEGACY_MODEL, row["dimensions"] or LEGACY_DIMENSIONS) for row in rows}
            if len(specs) > 1:
                self.logger.error("World embedding migration skipped world_id=%s reason=mixed_vector_specs", world_id)
                continue
            if specs:
                model, dimensions = next(iter(specs))
            else:
                continue
            attempt = self.store.get(world_id)
            key_id = (attempt or {}).get("key_id", "")
            profile = self._find_legacy_profile(key_id, model, dimensions)
            spec = self._profile_spec(profile, self._credential(key_id))
            world["embedding_profile_id"] = profile["id"]
            world["embedding_spec"] = spec
            atomic_json(path, world)
            self.logger.info("World embedding profile migrated world_id=%s dimensions=%d", world_id, dimensions)

    def _find_legacy_profile(self, key_id: str, model: str, dimensions: int) -> dict:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM embedding_profiles WHERE key_id=? AND model=? AND dimensions=? "
                "AND input_format_version=1 ORDER BY created_at LIMIT 1",
                (key_id, model, dimensions),
            ).fetchone()
            if row:
                return dict(row)
            identity = str(uuid4())
            stamp = _now()
            db.execute(
                "INSERT INTO embedding_profiles(id,name,key_id,model,dimensions,max_input_tokens,input_format_version,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,1,?,?)",
                (identity, f"Google {model} ({dimensions} dimensions)", key_id, model, dimensions,
                 LEGACY_INPUT_LIMIT, stamp, stamp),
            )
            return dict(db.execute("SELECT * FROM embedding_profiles WHERE id=?", (identity,)).fetchone())

    def _profile(self, profile_id: str, *, db=None) -> dict | None:
        if db is None:
            with self.store.connect() as connection:
                return self._profile(profile_id, db=connection)
        row = db.execute("SELECT * FROM embedding_profiles WHERE id=?", (profile_id,)).fetchone()
        return dict(row) if row else None

    def _credential(self, key_id: str) -> dict:
        if key_id and hasattr(self.store, "credential"):
            value = self.store.credential(key_id)
            if value:
                return value
        with self.store.connect() as db:
            row = db.execute(
                "SELECT k.id,k.name,k.provider,k.connection_id,k.base_url,c.enabled "
                "FROM provider_keys k LEFT JOIN provider_connections c ON c.id=k.connection_id WHERE k.id=?",
                (key_id,),
            ).fetchone() if key_id else None
        if row:
            value = dict(row)
            value["enabled"] = bool(value.get("enabled"))
            return value
        return {"id": key_id, "name": "Unavailable credential", "provider": "google",
                "enabled": False, "base_url": None}

    def _model(self, key_id: str, model_id: str) -> dict:
        value = self.store.model_for(key_id, model_id) if hasattr(self.store, "model_for") else None
        if value:
            return value
        credential = self._credential(key_id)
        if credential.get("provider") == "google" and model_id in {"gemini-embedding-2", "gemini-embedding-001"}:
            return {"id": model_id, "name": "Gemini Embedding 2" if model_id == "gemini-embedding-2" else "Gemini Embedding 001",
                    "capabilities": {"embeddings": True,
                                     "embedding": {"dimensions": [768, 1536, 3072], "max_dimensions": 3072,
                                                   "input_limit": 8192 if model_id == "gemini-embedding-2" else 2048}}}
        if credential.get("provider") == "openai":
            known = {
                "text-embedding-3-large": (3072, 8192),
                "text-embedding-3-small": (1536, 8192),
                "text-embedding-ada-002": (1536, 8192),
            }
            if model_id in known:
                dimensions, limit = known[model_id]
                return {"id": model_id, "name": model_id,
                        "capabilities": {"embeddings": True,
                                         "embedding": {"dimensions": [dimensions], "max_dimensions": dimensions,
                                                       "input_limit": limit}}}
        return {"id": model_id, "name": model_id,
                "capabilities": {"embeddings": None, "embedding": None}}

    def _discovered_model(self, key_id: str, model_id: str) -> dict | None:
        if hasattr(self.store, "model_for"):
            model = self.store.model_for(key_id, model_id)
            if model:
                return model
        if hasattr(self.store, "catalog"):
            models = self.store.catalog(key_id).get("models", [])
            return next((model for model in models if model.get("id") == model_id), None)
        return None

    def _has_access(self, key_id: str, credential: dict) -> bool:
        if credential.get("provider") == "openai_compatible":
            return bool(credential.get("base_url"))
        return bool(self.creation.vault.read(key_id))

    @staticmethod
    def _capabilities(model: dict) -> tuple[bool | None, int | None, int | None]:
        capabilities = model.get("capabilities") or {}
        supported = capabilities.get("embeddings")
        embedding = capabilities.get("embedding") or {}
        dimensions = embedding.get("max_dimensions")
        options = embedding.get("dimensions")
        if not dimensions and isinstance(options, list) and options:
            dimensions = max(item for item in options if isinstance(item, int) and item > 0)
        limit = embedding.get("input_limit")
        return supported, dimensions if isinstance(dimensions, int) else None, limit if isinstance(limit, int) else None

    def _worlds_for_profile(self, profile_id: str) -> list[dict]:
        found = []
        folder = self.root / "worlds"
        if folder.exists():
            for path in folder.glob("*/world.json"):
                world = json.loads(path.read_text(encoding="utf-8"))
                if world.get("embedding_profile_id") == profile_id:
                    found.append(world)
        return found

    def _attempts_for_profile(self, profile_id: str) -> list[dict]:
        return [value for value in self.store.pending()
                if value.get("embedding_profile_id") == profile_id]

    def list(self) -> dict:
        with self.store.connect() as db:
            rows = [dict(row) for row in db.execute(
                "SELECT * FROM embedding_profiles ORDER BY name COLLATE NOCASE,id")]
            state = dict(db.execute("SELECT * FROM embedding_profile_state WHERE id='current'").fetchone())
        return {
            "profiles": [self.public(profile) for profile in rows],
            "default_profile_id": state["default_profile_id"],
            "last_used_profile_id": state["last_used_profile_id"],
        }

    def public(self, profile: dict) -> dict:
        credential = self._credential(profile["key_id"])
        model = self._model(profile["key_id"], profile["model"])
        with self.store.connect() as db:
            state = db.execute("SELECT * FROM embedding_profile_state WHERE id='current'").fetchone()
        worlds = self._worlds_for_profile(profile["id"])
        pending = self._attempts_for_profile(profile["id"])
        uses = [{"id": world["id"], "name": world.get("name", "World")} for world in worlds]
        uses.extend({"id": attempt["id"], "name": attempt.get("name", "World")}
                    for attempt in pending)
        uses.sort(key=lambda item: (item["name"].casefold(), item["id"]))
        needs_preflight = (credential.get("provider") == "openai_compatible"
                           and self._capabilities(model)[1] is None)
        return {
            "id": profile["id"], "name": profile["name"], "key_id": profile["key_id"],
            "provider": credential.get("provider", "google"), "model": profile["model"],
            "model_name": model.get("name") or model.get("display_name") or profile["model"],
            "dimensions": profile["dimensions"], "max_input_tokens": profile["max_input_tokens"],
            "input_format_version": profile.get("input_format_version", 2),
            "is_default": bool(state and state["default_profile_id"] == profile["id"]),
            "usable": bool(credential.get("enabled") and self._has_access(profile["key_id"], credential)
                           and profile["dimensions"] and (not needs_preflight or profile.get("preflighted_at"))),
            "credential_name": credential.get("name"),
            "base_url": credential.get("base_url") if credential.get("provider") == "openai_compatible" else None,
            "world_count": len(uses), "pending_count": len(pending),
            "in_use": bool(uses), "worlds": uses,
            "preflighted_at": profile.get("preflighted_at"),
        }

    def _profile_spec(self, profile: dict, credential: dict) -> dict:
        provider = credential.get("provider", "google")
        return {
            "provider": provider,
            "model": profile["model"],
            "dimensions": profile["dimensions"],
            "max_input_tokens": profile["max_input_tokens"],
            "input_format_version": profile.get("input_format_version", 2),
            "base_url": credential.get("base_url") if provider == "openai_compatible" else None,
        }

    def world_profile(self, world: dict) -> dict | None:
        profile_id = world.get("embedding_profile_id")
        if not profile_id:
            return None
        profile = self._profile(profile_id)
        if profile:
            return {**self.public(profile), **(world.get("embedding_spec") or {})}
        return {"id": profile_id, **(world.get("embedding_spec") or {}),
                "name": "Embedding Profile", "usable": False}

    def snapshot(self, profile_id: str) -> tuple[dict, dict]:
        try:
            UUID(profile_id)
        except (ValueError, TypeError, AttributeError):
            raise CreationConflict("Choose an Embedding Profile before creating this World.") from None
        profile = self._profile(profile_id)
        if not profile:
            raise CreationConflict("The selected Embedding Profile no longer exists. Choose another one.")
        credential = self._credential(profile["key_id"])
        if credential.get("provider") not in EMBEDDING_PROVIDERS:
            raise CreationConflict("Choose a Google, OpenAI, or OpenAI-compatible connection for embeddings.")
        if not credential.get("enabled") or not self._has_access(profile["key_id"], credential):
            raise CreationConflict("The selected Embedding Profile needs an enabled connection with a saved key or Base URL.")
        return profile, self._profile_spec(profile, credential)

    def save(self, profile_id: str | None, name: str, key_id: str, model_id: str,
             selected_dimensions: int | None = None) -> dict:
        name = name.strip()
        if not name or len(name) > 100:
            raise ValueError("Give the Embedding Profile a name.")
        try:
            UUID(key_id)
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Choose a saved connection credential.") from None
        credential = self._credential(key_id)
        if credential.get("provider") not in EMBEDDING_PROVIDERS:
            raise ValueError("Choose a Google, OpenAI, or OpenAI-compatible connection for embeddings.")
        if not credential.get("enabled") or not self._has_access(key_id, credential):
            raise ValueError("Enable this connection and add its key or Base URL before creating an Embedding Profile.")
        model_id = model_id.strip()
        if not model_id or len(model_id) > 200:
            raise ValueError("Choose an embedding model from the selected connection.")
        model = self._discovered_model(key_id, model_id)
        if not model:
            raise ValueError("Choose a discovered model. Refresh this connection’s model list and try again.")
        supported, maximum_dimensions, input_limit = self._capabilities(model)
        if supported is False:
            raise ValueError("Choose a model that supports embeddings.")
        prior_profile = self._profile(profile_id) if profile_id else None
        if profile_id and not prior_profile:
            raise KeyError(profile_id)
        if selected_dimensions is not None:
            dimensions = selected_dimensions
        elif prior_profile and prior_profile["model"] == model_id:
            dimensions = prior_profile["dimensions"]
        else:
            dimensions = maximum_dimensions
        if dimensions is not None:
            if isinstance(dimensions, bool) or not isinstance(dimensions, int) or dimensions < 1:
                raise ValueError("Dimensions must be a positive whole number.")
            if maximum_dimensions and dimensions > maximum_dimensions:
                raise ValueError(f"Dimensions cannot exceed this model’s maximum of {maximum_dimensions}.")
            if credential["provider"] == "google" and model_id in {"gemini-embedding-2", "gemini-embedding-001"} and dimensions < 128:
                raise ValueError("This Google model requires at least 128 dimensions.")
            if credential["provider"] == "openai" and model_id == "text-embedding-ada-002" and dimensions != 1536:
                raise ValueError("This OpenAI model uses a fixed 1536 dimensions.")
        if profile_id:
            profile = prior_profile
            worlds = self._worlds_for_profile(profile_id)
            attempts = self._attempts_for_profile(profile_id)
            if attempts:
                if (key_id != profile["key_id"] or model_id != profile["model"]
                        or dimensions != profile["dimensions"]):
                    raise CreationConflict("Only the name can change while a World creation uses this profile.")
                input_limit = profile["max_input_tokens"]
            prior_credential = self._credential(profile["key_id"])
            if worlds:
                if model_id != profile["model"]:
                    raise CreationConflict("This Embedding Profile’s model is locked because a World uses it.")
                if credential.get("provider") != prior_credential.get("provider"):
                    raise CreationConflict("Choose a credential from the same provider to keep this World’s vectors compatible.")
                if credential.get("provider") == "openai_compatible" and credential.get("base_url") != prior_credential.get("base_url"):
                    raise CreationConflict("Choose a compatible credential with the same Base URL to keep this World’s vectors compatible.")
                if dimensions and profile["dimensions"] and dimensions != profile["dimensions"]:
                    raise CreationConflict("This Embedding Profile’s dimensions are locked because a World uses it.")
                dimensions = profile["dimensions"]
                input_limit = profile["max_input_tokens"]
            identity = profile_id
            created_at = profile["created_at"]
        else:
            identity = str(uuid4())
            created_at = _now()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO embedding_profiles(id,name,key_id,model,dimensions,max_input_tokens,preflighted_at,input_format_version,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,NULL,2,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,key_id=excluded.key_id,"
                "model=excluded.model,dimensions=excluded.dimensions,max_input_tokens=excluded.max_input_tokens,"
                "preflighted_at=CASE WHEN embedding_profiles.key_id=excluded.key_id AND embedding_profiles.model=excluded.model "
                "AND embedding_profiles.dimensions IS excluded.dimensions THEN embedding_profiles.preflighted_at ELSE NULL END,"
                "updated_at=excluded.updated_at",
                (identity, name, key_id, model_id, dimensions, input_limit, created_at, _now()),
            )
            db.execute(
                "UPDATE embedding_profile_state SET default_profile_id=COALESCE(default_profile_id,?) WHERE id='current'",
                (identity,),
            )
        profile = self._profile(identity)
        self.creation.logger.info("Embedding Profile saved profile_id=%s provider=%s model=%s", identity,
                                  credential["provider"], model_id)
        return self.public(profile)

    def set_default(self, profile_id: str | None):
        if profile_id is not None and not self._profile(profile_id):
            raise KeyError(profile_id)
        with self.store.connect() as db:
            db.execute("UPDATE embedding_profile_state SET default_profile_id=? WHERE id='current'", (profile_id,))
        return self.list()

    def record_used(self, profile_id: str):
        with self.store.connect() as db:
            db.execute("UPDATE embedding_profile_state SET last_used_profile_id=? WHERE id='current'", (profile_id,))

    def delete(self, profile_id: str):
        profile = self._profile(profile_id)
        if not profile:
            raise KeyError(profile_id)
        if self._worlds_for_profile(profile_id):
            raise CreationConflict("This Embedding Profile is used by a World and cannot be deleted.")
        if self._attempts_for_profile(profile_id):
            raise CreationConflict("Discard the World creation that uses this profile before deleting it.")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state = db.execute("SELECT * FROM embedding_profile_state WHERE id='current'").fetchone()
            if state["default_profile_id"] == profile_id:
                next_row = db.execute(
                    "SELECT id FROM embedding_profiles WHERE id<>? ORDER BY name COLLATE NOCASE,id LIMIT 1",
                    (profile_id,),
                ).fetchone()
                default_id = next_row["id"] if next_row else None
            else:
                default_id = state["default_profile_id"]
            last_used_id = None if state["last_used_profile_id"] == profile_id else state["last_used_profile_id"]
            db.execute("DELETE FROM embedding_profiles WHERE id=?", (profile_id,))
            db.execute("UPDATE embedding_profile_state SET default_profile_id=?,last_used_profile_id=? WHERE id='current'",
                       (default_id, last_used_id))
        self.creation.logger.info("Embedding Profile deleted profile_id=%s", profile_id)
        return {"deleted": True}
