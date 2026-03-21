"""App-wide constants, path helpers, and settings I/O."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent.parent          # sovereign/
BACKEND_DIR = ROOT_DIR / "backend"
SETTINGS_DIR = ROOT_DIR / "settings"
SAVED_WORLDS_DIR = ROOT_DIR / "saved_worlds"

SETTINGS_FILE = SETTINGS_DIR / "settings.json"
DEFAULT_PROMPTS_FILE = SETTINGS_DIR / "default_prompts.json"

# Ensure directories exist
SAVED_WORLDS_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_DIR.mkdir(parents=True, exist_ok=True)

# ── Default settings template ──────────────────────────────────────────
_DEFAULT_SETTINGS = {
    "api_keys": [],
    "key_rotation_mode": "FAIL_OVER",
    "default_model_flash": "gemini-flash-lite-latest",
    "default_model_chat": "gemini-flash-latest",
    "default_model_entity_chooser": "gemini-flash-latest",
    "default_model_entity_combiner": "gemini-flash-lite-latest",
    "embedding_model": "gemini-embedding-002-preview",
    "chunk_size_chars": 4000,
    "chunk_overlap_chars": 150,
    "retrieval_top_k_chunks": 5,
    "retrieval_graph_hops": 2,
    "retrieval_max_nodes": 50,
    "retrieval_context_messages": 3,
    "chat_history_messages": 1000,
    "entity_resolution_top_k": 50,
    "glean_amount": 1,
    "extract_entity_types": True,
    "graph_architect_prompt": None,
    "entity_resolution_chooser_prompt": None,
    "entity_resolution_combiner_prompt": None,
    "chat_system_prompt": None,
    "disable_safety_filters": False,
    "ui_theme": "dark",
    "graph_extraction_concurrency": 4,
    "graph_extraction_cooldown_seconds": 0,
    "embedding_concurrency": 8,
    "embedding_cooldown_seconds": 0,
    # Chat provider selection
    "chat_provider": "gemini",
    "intenserp_base_url": "http://127.0.0.1:7777/v1",
    "intenserp_model_id": "glm-chat",
}

INGEST_SETTINGS_KEYS = (
    "chunk_size_chars",
    "chunk_overlap_chars",
    "embedding_model",
)


def _coerce_int(value: object, default: int, *, minimum: int | None = None) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = int(default)
    if minimum is not None:
        normalized = max(int(minimum), normalized)
    return normalized


def _coerce_float(value: object, default: float, *, minimum: float | None = None) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        normalized = float(default)
    if minimum is not None:
        normalized = max(float(minimum), normalized)
    return normalized


def sanitize_settings(settings: dict) -> dict:
    """Normalize runtime/persisted settings so invalid stage limits cannot leak into execution."""
    data = dict(settings)
    data["api_keys"] = normalize_api_key_entries(data.get("api_keys"))
    data["ui_theme"] = "light" if str(data.get("ui_theme", _DEFAULT_SETTINGS["ui_theme"])).lower() == "light" else "dark"
    graph_default = data.get("ingestion_concurrency", _DEFAULT_SETTINGS["graph_extraction_concurrency"])
    data["graph_extraction_concurrency"] = _coerce_int(
        data.get("graph_extraction_concurrency", graph_default),
        _DEFAULT_SETTINGS["graph_extraction_concurrency"],
        minimum=1,
    )
    data["graph_extraction_cooldown_seconds"] = _coerce_float(
        data.get("graph_extraction_cooldown_seconds", _DEFAULT_SETTINGS["graph_extraction_cooldown_seconds"]),
        _DEFAULT_SETTINGS["graph_extraction_cooldown_seconds"],
        minimum=0.0,
    )
    data["embedding_concurrency"] = _coerce_int(
        data.get("embedding_concurrency", _DEFAULT_SETTINGS["embedding_concurrency"]),
        _DEFAULT_SETTINGS["embedding_concurrency"],
        minimum=1,
    )
    data["embedding_cooldown_seconds"] = _coerce_float(
        data.get("embedding_cooldown_seconds", _DEFAULT_SETTINGS["embedding_cooldown_seconds"]),
        _DEFAULT_SETTINGS["embedding_cooldown_seconds"],
        minimum=0.0,
    )
    return data


def normalize_api_key_entries(value: object) -> list[dict[str, object]]:
    """Normalize saved API keys into `{value, enabled}` entries."""
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, object]] = []
    for item in value:
        if isinstance(item, str):
            key_value = item.strip()
            if key_value:
                normalized.append({"value": key_value, "enabled": True})
            continue

        if not isinstance(item, dict):
            continue

        raw_value = item.get("value")
        if not isinstance(raw_value, str):
            continue
        key_value = raw_value.strip()
        if not key_value:
            continue

        normalized.append(
            {
                "value": key_value,
                "enabled": bool(item.get("enabled", True)),
            }
        )

    return normalized


def get_enabled_api_keys(settings: dict | None = None) -> list[str]:
    """Return enabled saved API keys in persisted order."""
    settings_data = settings or load_settings()
    return [
        str(entry["value"])
        for entry in normalize_api_key_entries(settings_data.get("api_keys"))
        if bool(entry.get("enabled", True))
    ]


def load_settings() -> dict:
    """Load settings from disk, creating defaults if missing."""
    if not SETTINGS_FILE.exists():
        defaults = dict(_DEFAULT_SETTINGS)
        defaults["retrieval_entry_top_k_nodes"] = defaults["retrieval_top_k_chunks"]
        save_settings(defaults)
        return sanitize_settings(defaults)
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Fill missing keys with defaults (no auto-migrate, just sensible defaults)
    for k, v in _DEFAULT_SETTINGS.items():
        if k not in data:
            data[k] = v
    if "graph_extraction_concurrency" not in data:
        data["graph_extraction_concurrency"] = int(
            data.get("ingestion_concurrency", _DEFAULT_SETTINGS["graph_extraction_concurrency"])
        )
    if "graph_extraction_cooldown_seconds" not in data:
        data["graph_extraction_cooldown_seconds"] = _DEFAULT_SETTINGS["graph_extraction_cooldown_seconds"]
    if "embedding_concurrency" not in data:
        data["embedding_concurrency"] = _DEFAULT_SETTINGS["embedding_concurrency"]
    if "embedding_cooldown_seconds" not in data:
        data["embedding_cooldown_seconds"] = _DEFAULT_SETTINGS["embedding_cooldown_seconds"]
    if "retrieval_entry_top_k_nodes" not in data:
        if "retrieval_entry_top_k_chunks" in data:
            data["retrieval_entry_top_k_nodes"] = data["retrieval_entry_top_k_chunks"]
        else:
            data["retrieval_entry_top_k_nodes"] = data.get(
                "retrieval_top_k_chunks",
                _DEFAULT_SETTINGS["retrieval_top_k_chunks"],
            )
    return sanitize_settings(data)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_settings(settings: dict) -> None:
    settings = sanitize_settings(settings)
    """Atomic write: .tmp → os.replace()."""
    tmp = SETTINGS_FILE.with_suffix(".tmp.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    os.replace(str(tmp), str(SETTINGS_FILE))


def parse_csv_env(value: str | None, *, default: list[str]) -> list[str]:
    """Parse a comma-separated env var into a normalized list of strings."""
    if not value or not value.strip():
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


def load_default_prompts() -> dict:
    """Load the read-only default prompts file."""
    with open(DEFAULT_PROMPTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_prompt(key: str) -> str:
    """Load a prompt: settings override → default_prompts fallback → crash."""
    settings = load_settings()
    if settings.get(key):
        return settings[key]
    defaults = load_default_prompts()
    if key not in defaults:
        raise ValueError(f"Prompt key '{key}' not found in settings or default_prompts.json")
    return defaults[key]


def world_dir(world_id: str) -> Path:
    """Return the directory path for a specific world."""
    return SAVED_WORLDS_DIR / world_id


def world_meta_path(world_id: str) -> Path:
    return world_dir(world_id) / "meta.json"


def load_world_meta(world_id: str) -> dict | None:
    """Load world metadata or return None when unavailable/corrupt."""
    path = world_meta_path(world_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def get_default_ingest_settings(settings: dict | None = None) -> dict:
    """Return global default ingest settings for worlds that are not yet locked."""
    settings_data = settings or load_settings()
    return {
        "chunk_size_chars": int(settings_data.get("chunk_size_chars", _DEFAULT_SETTINGS["chunk_size_chars"])),
        "chunk_overlap_chars": int(settings_data.get("chunk_overlap_chars", _DEFAULT_SETTINGS["chunk_overlap_chars"])),
        "embedding_model": str(settings_data.get("embedding_model", _DEFAULT_SETTINGS["embedding_model"])),
        "locked_at": None,
        "last_ingest_settings_at": None,
    }


def get_world_ingest_settings(*, world_id: str | None = None, meta: dict | None = None) -> dict:
    """
    Return effective per-world ingest settings.

    Missing chunk settings fall back to current global defaults. This lets
    not-yet-ingested worlds track globals until the first explicit ingest lock.
    """
    meta_data = meta if meta is not None else (load_world_meta(world_id) if world_id else None)
    defaults = get_default_ingest_settings()
    stored = {}
    if meta_data:
        raw = meta_data.get("ingest_settings")
        if isinstance(raw, dict):
            stored = raw
        legacy_embedding = meta_data.get("embedding_model")
        legacy_world_has_locked_context = bool(
            stored.get("locked_at")
            or stored.get("last_ingest_settings_at")
            or meta_data.get("total_chunks")
            or meta_data.get("ingestion_status") not in {"pending", None}
        )
        if legacy_embedding and legacy_world_has_locked_context and not stored.get("embedding_model"):
            stored = {**stored, "embedding_model": legacy_embedding}

    output = dict(defaults)
    for key in INGEST_SETTINGS_KEYS:
        value = stored.get(key)
        if value in (None, ""):
            continue
        if key in {"chunk_size_chars", "chunk_overlap_chars"}:
            try:
                output[key] = int(value)
            except (TypeError, ValueError):
                continue
        else:
            output[key] = str(value)

    locked_at = stored.get("locked_at")
    if locked_at:
        output["locked_at"] = str(locked_at)
    last_ingest_settings_at = stored.get("last_ingest_settings_at")
    if last_ingest_settings_at:
        output["last_ingest_settings_at"] = str(last_ingest_settings_at)
    return output


def set_world_ingest_settings(
    world_id: str,
    ingest_settings: dict,
    *,
    lock: bool = False,
    touch: bool = True,
) -> dict | None:
    """Persist normalized ingest settings onto world metadata."""
    path = world_meta_path(world_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    current = get_world_ingest_settings(meta=meta)
    updated = dict(current)
    for key in INGEST_SETTINGS_KEYS:
        value = ingest_settings.get(key)
        if value in (None, ""):
            continue
        if key in {"chunk_size_chars", "chunk_overlap_chars"}:
            try:
                updated[key] = int(value)
            except (TypeError, ValueError):
                continue
        else:
            updated[key] = str(value)

    now = _now_iso()
    updated["locked_at"] = updated.get("locked_at") or (now if lock else None)
    if touch:
        updated["last_ingest_settings_at"] = now

    meta["ingest_settings"] = updated
    meta["embedding_model"] = updated["embedding_model"]

    tmp = path.with_suffix(".tmp.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    os.replace(str(tmp), str(path))
    return updated


def get_world_embedding_model(world_id: str) -> str:
    """Prefer the embedding model recorded on the world over current global settings."""
    return get_world_ingest_settings(world_id=world_id)["embedding_model"]


def set_world_embedding_model(world_id: str, embedding_model: str) -> None:
    """Persist embedding model on world metadata when the world exists."""
    set_world_ingest_settings(world_id, {"embedding_model": embedding_model}, lock=False, touch=False)


def world_graph_path(world_id: str) -> Path:
    return world_dir(world_id) / "world_graph.gexf"


def world_checkpoint_path(world_id: str) -> Path:
    return world_dir(world_id) / "checkpoint.json"


def world_log_path(world_id: str) -> Path:
    return world_dir(world_id) / "ingestion_log.json"


def world_sources_dir(world_id: str) -> Path:
    d = world_dir(world_id) / "sources"
    d.mkdir(parents=True, exist_ok=True)
    return d


def world_chroma_dir(world_id: str) -> Path:
    d = world_dir(world_id) / "chroma"
    d.mkdir(parents=True, exist_ok=True)
    return d
