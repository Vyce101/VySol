"""App-wide constants, provider capabilities, and settings I/O."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .ai_catalog import (
    SLOT_CHAT as AI_SLOT_CHAT,
    SLOT_EMBEDDING as AI_SLOT_EMBEDDING,
    SLOT_ENTITY_CHOOSER as AI_SLOT_ENTITY_CHOOSER,
    SLOT_ENTITY_COMBINER as AI_SLOT_ENTITY_COMBINER,
    SLOT_FLASH as AI_SLOT_FLASH,
    TASK_CHAT,
    TASK_EMBEDDING,
    build_ai_catalog,
    get_default_slot_configs,
    get_provider_manifest,
    get_provider_manifest_entry,
    get_slot_param_defs,
    list_provider_ids,
    normalize_slot_config,
    provider_is_custom_model_first,
    provider_is_selectable,
    provider_supports_embeddings,
    validate_slot_config,
)
from .atomic_json import dump_json_atomic

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
SETTINGS_DIR = ROOT_DIR / "settings"
SAVED_WORLDS_DIR = ROOT_DIR / "saved_worlds"

SETTINGS_FILE = SETTINGS_DIR / "settings.json"
DEFAULT_PROMPTS_FILE = SETTINGS_DIR / "default_prompts.json"

SAVED_WORLDS_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_DIR.mkdir(parents=True, exist_ok=True)

SETTINGS_SCHEMA_VERSION = 3
DEFAULT_PRESET_NAME = "Default"
_SETTINGS_STATE_LOCK = threading.RLock()

PROVIDER_GEMINI = "gemini"
PROVIDER_GROQ = "groq"
PROVIDER_OPENAI_COMPATIBLE = "openai_compatible"
PROVIDER_INTENSERP = "intenserp"

SLOT_FLASH = AI_SLOT_FLASH
SLOT_CHAT = AI_SLOT_CHAT
SLOT_ENTITY_CHOOSER = AI_SLOT_ENTITY_CHOOSER
SLOT_ENTITY_COMBINER = AI_SLOT_ENTITY_COMBINER
SLOT_EMBEDDING = AI_SLOT_EMBEDDING

PROVIDER_REGISTRY: dict[str, dict[str, Any]] = get_provider_manifest()

PROMPT_KEYS = (
    "graph_architect_prompt",
    "graph_architect_glean_prompt",
    "entity_resolution_chooser_prompt",
    "entity_resolution_combiner_prompt",
    "chat_system_prompt",
)

TOP_LEVEL_SETTINGS_DEFAULTS = {
    "chunk_size_chars": 4000,
    "chunk_overlap_chars": 150,
    "retrieval_top_k_chunks": 5,
    "retrieval_graph_hops": 2,
    "retrieval_max_nodes": 50,
    "retrieval_max_neighbors_per_node": 15,
    "retrieval_max_node_description_chars": 0,
    "retrieval_context_char_limit": 0,
    "retrieval_context_messages": 3,
    "chat_history_messages": 1000,
    "entity_resolution_top_k": 50,
    "glean_amount": 1,
    "extract_entity_types": True,
    "retrieval_entry_top_k_nodes": 5,
}

PRESET_SETTINGS_DEFAULTS = {
    "key_rotation_mode": "FAIL_OVER",
    "slots": get_default_slot_configs(),
    "ui_theme": "dark",
    "graph_extraction_concurrency": 4,
    "graph_extraction_cooldown_seconds": 0.0,
    "embedding_concurrency": 8,
    "embedding_cooldown_seconds": 0.0,
}

CONFIGURATION_PRESET_KEYS = tuple(PRESET_SETTINGS_DEFAULTS.keys())
TOP_LEVEL_SETTINGS_KEYS = tuple(TOP_LEVEL_SETTINGS_DEFAULTS.keys())

EFFECTIVE_SETTINGS_DEFAULTS = {
    **TOP_LEVEL_SETTINGS_DEFAULTS,
    **PRESET_SETTINGS_DEFAULTS,
    "graph_architect_prompt": None,
    "graph_architect_glean_prompt": None,
    "entity_resolution_chooser_prompt": None,
    "entity_resolution_combiner_prompt": None,
    "chat_system_prompt": None,
}

INGEST_SETTINGS_KEYS = (
    "chunk_size_chars",
    "chunk_overlap_chars",
    "embedding_provider",
    "embedding_model",
    "embedding_params",
    "glean_amount",
)

WORLD_INGEST_PROMPT_KEYS = (
    "graph_architect_prompt",
    "graph_architect_glean_prompt",
    "entity_resolution_chooser_prompt",
    "entity_resolution_combiner_prompt",
)

LEGACY_REMOVED_KEYS = {
    "use_single_agent",
    "enable_claims",
    "default_model_scribe",
    "entity_architect_prompt",
    "relationship_architect_prompt",
    "claim_architect_prompt",
    "scribe_prompt",
    "ingestion_concurrency",
}

LEGACY_SLOT_KEY_TO_SETTING_PREFIX = {
    SLOT_FLASH: "default_model_flash",
    SLOT_CHAT: "default_model_chat",
    SLOT_ENTITY_CHOOSER: "default_model_entity_chooser",
    SLOT_ENTITY_COMBINER: "default_model_entity_combiner",
}


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


def _coerce_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
    if isinstance(value, (int, float)):
        return value != 0
    if value is None:
        return bool(default)
    return bool(value)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_csv_env(value: str | None, *, default: list[str]) -> list[str]:
    """Parse a comma-separated env var into a normalized list of strings."""
    if not value or not value.strip():
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


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


def _mask_secret(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if len(raw) <= 8:
        return "*" * len(raw)
    return f"{'*' * max(4, len(raw) - 4)}{raw[-4:]}"


def _default_provider_label(provider: str, index: int) -> str:
    info = PROVIDER_REGISTRY.get(provider, {})
    display_name = str(info.get("display_name") or provider.title())
    return f"{display_name} {index}"


def _normalize_provider_family(slot: str, value: object) -> str:
    normalized = str(value or "").strip()
    if normalized in PROVIDER_REGISTRY:
        provider_entry = PROVIDER_REGISTRY[normalized]
        if slot in provider_entry.get("supported_slots", set()):
            return normalized
    return get_default_slot_configs()[slot]["provider"]


def _normalize_openai_compatible_provider(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in PROVIDER_REGISTRY:
        return normalized
    return PROVIDER_OPENAI_COMPATIBLE


def _normalize_provider_credential_entries(provider: str, value: object) -> list[dict[str, Any]]:
    if provider not in PROVIDER_REGISTRY:
        return []

    if not isinstance(value, list):
        return []

    normalized: list[dict[str, Any]] = []
    field_names = {field["name"] for field in PROVIDER_REGISTRY[provider].get("credential_fields", ())}
    secret_fields = {
        field["name"]
        for field in PROVIDER_REGISTRY[provider].get("credential_fields", ())
        if field.get("secret")
    }

    for index, item in enumerate(value, start=1):
        if isinstance(item, str):
            if "api_key" not in field_names:
                continue
            entry: dict[str, Any] = {
                "id": uuid4().hex,
                "label": _default_provider_label(provider, index),
                "enabled": True,
                "api_key": item.strip(),
            }
        elif isinstance(item, dict):
            entry = {
                "id": str(item.get("id") or uuid4().hex),
                "label": str(item.get("label") or "").strip() or _default_provider_label(provider, index),
                "enabled": _coerce_bool(item.get("enabled", True), True),
            }
            for field_name in field_names:
                raw_value = item.get(field_name)
                if raw_value is None:
                    continue
                entry[field_name] = str(raw_value).strip()
        else:
            continue

        valid = False
        for field_name in field_names:
            value_str = str(entry.get(field_name) or "").strip()
            if not value_str:
                continue
            valid = True
            if field_name in secret_fields:
                entry[field_name] = value_str
            else:
                entry[field_name] = value_str.rstrip("/")
        if not valid:
            continue
        normalized.append(entry)

    return normalized


def _normalize_provider_credentials_map(value: object) -> dict[str, list[dict[str, Any]]]:
    raw = value if isinstance(value, dict) else {}
    normalized: dict[str, list[dict[str, Any]]] = {}
    for provider in PROVIDER_REGISTRY:
        normalized[provider] = _normalize_provider_credential_entries(provider, raw.get(provider))
    return normalized


def _default_raw_settings() -> dict[str, Any]:
    return {
        "schema_version": SETTINGS_SCHEMA_VERSION,
        "active_settings_preset_id": None,
        "settings_presets": [],
        "provider_credentials": {provider: [] for provider in PROVIDER_REGISTRY},
        **TOP_LEVEL_SETTINGS_DEFAULTS,
        **{key: None for key in PROMPT_KEYS},
    }


def _build_default_preset_values() -> dict[str, Any]:
    return dict(PRESET_SETTINGS_DEFAULTS)


def _build_default_preset(*, preset_id: str | None = None, name: str | None = None) -> dict[str, Any]:
    return {
        "id": preset_id or uuid4().hex,
        "name": str(name or DEFAULT_PRESET_NAME),
        "locked": True,
        "values": _build_default_preset_values(),
    }


def _normalize_slot_map(value: object) -> dict[str, dict[str, Any]]:
    incoming = value if isinstance(value, dict) else {}
    defaults = get_default_slot_configs()
    normalized: dict[str, dict[str, Any]] = {}
    for slot in defaults:
        normalized[slot] = normalize_slot_config(slot, incoming.get(slot))
    return normalized


def _build_slot_config_from_legacy(incoming: dict[str, Any], slot: str) -> dict[str, Any]:
    default_slot = get_default_slot_configs()[slot]
    prefix = LEGACY_SLOT_KEY_TO_SETTING_PREFIX.get(slot)
    if slot == SLOT_EMBEDDING:
        provider = str(incoming.get("embedding_provider") or incoming.get("embedding_openai_compatible_provider") or default_slot["provider"]).strip()
        model_name = str(incoming.get("embedding_model") or default_slot["model"]).strip()
        params = incoming.get("embedding_params")
        return normalize_slot_config(
            slot,
            {
                "provider": provider,
                "model": model_name,
                "task": TASK_EMBEDDING,
                "params": params if isinstance(params, dict) else default_slot.get("params", {}),
            },
        )

    provider = str(incoming.get(f"{prefix}_provider") or default_slot["provider"]).strip()
    legacy_openai_provider = str(incoming.get(f"{prefix}_openai_compatible_provider") or "").strip()
    if provider == "openai_compatible" and legacy_openai_provider:
        provider = legacy_openai_provider
    params = dict(default_slot.get("params", {}))
    model_name = str(incoming.get(prefix) or default_slot["model"]).strip()
    legacy_reasoning = str(incoming.get(f"{prefix}_groq_reasoning_effort") or "").strip()
    legacy_thinking_level = str(incoming.get(f"{prefix}_thinking_level") or "").strip()
    legacy_thinking_manual = str(incoming.get(f"{prefix}_thinking_manual") or "").strip()
    if legacy_reasoning:
        params["reasoning_effort"] = legacy_reasoning
    elif legacy_thinking_level:
        params["reasoning_effort"] = "high" if legacy_thinking_level == "minimal" else legacy_thinking_level
    if legacy_thinking_manual:
        try:
            params["thinking"] = {"budget_tokens": int(legacy_thinking_manual)}
        except ValueError:
            params["thinking"] = {"preset": legacy_thinking_manual}
    if slot == SLOT_CHAT:
        if "groq_chat_include_reasoning" in incoming and bool(incoming.get("groq_chat_include_reasoning")):
            params["reasoning_effort"] = str(params.get("reasoning_effort") or "medium")
        if "gemini_chat_send_thinking" in incoming and bool(incoming.get("gemini_chat_send_thinking")):
            params.setdefault("reasoning_effort", "high")
        if "gemini_disable_safety_filters" in incoming and bool(incoming.get("gemini_disable_safety_filters")):
            params.setdefault(
                "safety_settings",
                [
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                ],
            )
    return normalize_slot_config(
        slot,
        {
            "provider": provider,
            "model": model_name,
            "task": TASK_CHAT,
            "params": params,
        },
    )


def _apply_legacy_slot_aliases(values: dict[str, Any]) -> dict[str, Any]:
    incoming = dict(values)
    slot_map = incoming.get("slots")
    if isinstance(slot_map, dict):
        normalized_slots = _normalize_slot_map(slot_map)
    else:
        normalized_slots = {
            slot: _build_slot_config_from_legacy(incoming, slot)
            for slot in get_default_slot_configs()
        }
    incoming["slots"] = normalized_slots
    return incoming


def _build_legacy_compat_fields_from_slots(slots: dict[str, dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for slot, config in slots.items():
        provider = str(config.get("provider") or "")
        model_name = str(config.get("model") or "")
        params = dict(config.get("params") or {})
        if slot == SLOT_EMBEDDING:
            output["embedding_provider"] = provider
            output["embedding_openai_compatible_provider"] = provider
            output["embedding_model"] = model_name
            output["embedding_params"] = params
            continue

        prefix = LEGACY_SLOT_KEY_TO_SETTING_PREFIX[slot]
        output[prefix] = model_name
        output[f"{prefix}_provider"] = provider
        output[f"{prefix}_openai_compatible_provider"] = provider
        output[f"{prefix}_groq_reasoning_effort"] = str(params.get("reasoning_effort") or "")
        output[f"{prefix}_thinking_level"] = str(params.get("reasoning_effort") or "")
        thinking = params.get("thinking")
        output[f"{prefix}_thinking_manual"] = ""
        if isinstance(thinking, dict):
            budget = thinking.get("budget_tokens")
            if budget is not None:
                output[f"{prefix}_thinking_manual"] = str(budget)

    chat_params = dict(slots.get(SLOT_CHAT, {}).get("params") or {})
    output["gemini_chat_send_thinking"] = bool(chat_params.get("reasoning_effort"))
    output["groq_chat_include_reasoning"] = bool(chat_params.get("reasoning_effort"))
    output["gemini_disable_safety_filters"] = bool(chat_params.get("safety_settings"))
    output["chat_provider"] = str(slots.get(SLOT_CHAT, {}).get("provider") or PROVIDER_GEMINI)
    return output


def _normalize_preset_values(value: object) -> dict[str, Any]:
    incoming = _apply_legacy_slot_aliases(value if isinstance(value, dict) else {})
    normalized = dict(PRESET_SETTINGS_DEFAULTS)
    normalized["key_rotation_mode"] = (
        "ROUND_ROBIN" if str(incoming.get("key_rotation_mode", PRESET_SETTINGS_DEFAULTS["key_rotation_mode"])).strip().upper() == "ROUND_ROBIN" else "FAIL_OVER"
    )
    normalized["ui_theme"] = (
        "light" if str(incoming.get("ui_theme", PRESET_SETTINGS_DEFAULTS["ui_theme"])).strip().lower() == "light" else "dark"
    )
    normalized["graph_extraction_concurrency"] = _coerce_int(
        incoming.get("graph_extraction_concurrency"),
        PRESET_SETTINGS_DEFAULTS["graph_extraction_concurrency"],
        minimum=1,
    )
    normalized["graph_extraction_cooldown_seconds"] = _coerce_float(
        incoming.get("graph_extraction_cooldown_seconds"),
        PRESET_SETTINGS_DEFAULTS["graph_extraction_cooldown_seconds"],
        minimum=0.0,
    )
    normalized["embedding_concurrency"] = _coerce_int(
        incoming.get("embedding_concurrency"),
        PRESET_SETTINGS_DEFAULTS["embedding_concurrency"],
        minimum=1,
    )
    normalized["embedding_cooldown_seconds"] = _coerce_float(
        incoming.get("embedding_cooldown_seconds"),
        PRESET_SETTINGS_DEFAULTS["embedding_cooldown_seconds"],
        minimum=0.0,
    )
    normalized["slots"] = _normalize_slot_map(incoming.get("slots"))
    normalized.update(_build_legacy_compat_fields_from_slots(normalized["slots"]))
    return normalized


def sanitize_settings(settings: dict) -> dict:
    """Normalize a flat settings dict without mutating persisted structure helpers."""
    data = dict(EFFECTIVE_SETTINGS_DEFAULTS)
    incoming = _apply_legacy_slot_aliases(dict(settings or {}))

    top_level_subset = {key: incoming.get(key, data[key]) for key in TOP_LEVEL_SETTINGS_KEYS}
    preset_subset = {key: incoming.get(key, data[key]) for key in CONFIGURATION_PRESET_KEYS}

    for key, value in top_level_subset.items():
        data[key] = value
    for key, value in _normalize_preset_values(preset_subset).items():
        data[key] = value

    data["chunk_size_chars"] = _coerce_int(data.get("chunk_size_chars"), TOP_LEVEL_SETTINGS_DEFAULTS["chunk_size_chars"], minimum=1)
    data["chunk_overlap_chars"] = _coerce_int(
        data.get("chunk_overlap_chars"),
        TOP_LEVEL_SETTINGS_DEFAULTS["chunk_overlap_chars"],
        minimum=0,
    )
    data["retrieval_top_k_chunks"] = _coerce_int(
        data.get("retrieval_top_k_chunks"),
        TOP_LEVEL_SETTINGS_DEFAULTS["retrieval_top_k_chunks"],
        minimum=1,
    )
    data["retrieval_graph_hops"] = _coerce_int(
        data.get("retrieval_graph_hops"),
        TOP_LEVEL_SETTINGS_DEFAULTS["retrieval_graph_hops"],
        minimum=0,
    )
    data["retrieval_max_nodes"] = _coerce_int(
        data.get("retrieval_max_nodes"),
        TOP_LEVEL_SETTINGS_DEFAULTS["retrieval_max_nodes"],
        minimum=1,
    )
    data["retrieval_max_neighbors_per_node"] = _coerce_int(
        data.get("retrieval_max_neighbors_per_node"),
        TOP_LEVEL_SETTINGS_DEFAULTS["retrieval_max_neighbors_per_node"],
        minimum=1,
    )
    data["retrieval_max_node_description_chars"] = _coerce_int(
        data.get("retrieval_max_node_description_chars"),
        TOP_LEVEL_SETTINGS_DEFAULTS["retrieval_max_node_description_chars"],
        minimum=0,
    )
    data["retrieval_context_char_limit"] = _coerce_int(
        data.get("retrieval_context_char_limit"),
        TOP_LEVEL_SETTINGS_DEFAULTS["retrieval_context_char_limit"],
        minimum=0,
    )
    data["retrieval_context_messages"] = _coerce_int(
        data.get("retrieval_context_messages"),
        TOP_LEVEL_SETTINGS_DEFAULTS["retrieval_context_messages"],
        minimum=1,
    )
    data["chat_history_messages"] = _coerce_int(
        data.get("chat_history_messages"),
        TOP_LEVEL_SETTINGS_DEFAULTS["chat_history_messages"],
        minimum=1,
    )
    data["entity_resolution_top_k"] = _coerce_int(
        data.get("entity_resolution_top_k"),
        TOP_LEVEL_SETTINGS_DEFAULTS["entity_resolution_top_k"],
        minimum=1,
    )
    data["glean_amount"] = _coerce_int(
        data.get("glean_amount"),
        TOP_LEVEL_SETTINGS_DEFAULTS["glean_amount"],
        minimum=0,
    )
    data["extract_entity_types"] = _coerce_bool(
        data.get("extract_entity_types"),
        TOP_LEVEL_SETTINGS_DEFAULTS["extract_entity_types"],
    )
    legacy_entry_top_k = incoming.get("retrieval_entry_top_k_chunks", incoming.get("retrieval_top_k_chunks"))
    data["retrieval_entry_top_k_nodes"] = _coerce_int(
        incoming.get("retrieval_entry_top_k_nodes", legacy_entry_top_k),
        TOP_LEVEL_SETTINGS_DEFAULTS["retrieval_entry_top_k_nodes"],
        minimum=1,
    )

    for key in PROMPT_KEYS:
        raw_value = incoming.get(key)
        if raw_value is None:
            data[key] = None
        else:
            normalized = str(raw_value).strip()
            data[key] = normalized if normalized else None

    data.update(_build_legacy_compat_fields_from_slots(data["slots"]))
    data["disable_safety_filters"] = data["gemini_disable_safety_filters"]
    data["api_keys"] = normalize_api_key_entries(incoming.get("api_keys"))
    return data


def _normalize_top_level_value(key: str, value: Any) -> Any:
    if key in {"chunk_size_chars", "chunk_overlap_chars", "retrieval_top_k_chunks", "retrieval_graph_hops", "retrieval_max_nodes", "retrieval_max_neighbors_per_node", "retrieval_max_node_description_chars", "retrieval_context_char_limit", "retrieval_context_messages", "chat_history_messages", "entity_resolution_top_k", "glean_amount", "retrieval_entry_top_k_nodes"}:
        default = int(TOP_LEVEL_SETTINGS_DEFAULTS.get(key, 0))
        minimum = 1 if key not in {"chunk_overlap_chars", "retrieval_graph_hops", "retrieval_max_node_description_chars", "retrieval_context_char_limit", "glean_amount"} else 0
        return _coerce_int(value, default, minimum=minimum)
    if key == "extract_entity_types":
        return _coerce_bool(value, TOP_LEVEL_SETTINGS_DEFAULTS[key])
    if key in PROMPT_KEYS:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized if normalized else None
    return value


def _apply_chat_provider_alias(target: dict[str, Any], provider_value: object) -> None:
    normalized = str(provider_value or "").strip().lower()
    if normalized == PROVIDER_INTENSERP:
        target["default_model_chat_provider"] = PROVIDER_INTENSERP
    elif normalized == PROVIDER_GROQ:
        target["default_model_chat_provider"] = "openai_compatible"
        target["default_model_chat_openai_compatible_provider"] = PROVIDER_GROQ
    elif normalized == "openai_compatible":
        target["default_model_chat_provider"] = "openai_compatible"
        target["default_model_chat_openai_compatible_provider"] = _normalize_openai_compatible_provider(
            target.get("default_model_chat_openai_compatible_provider")
        )
    else:
        target["default_model_chat_provider"] = PROVIDER_GEMINI


def _build_legacy_provider_credentials_from_api_keys(
    api_keys_value: object,
    *,
    existing_entries: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    normalized_keys = normalize_api_key_entries(api_keys_value)
    existing = list(existing_entries or [])
    output: list[dict[str, Any]] = []
    for index, entry in enumerate(normalized_keys, start=1):
        matching_existing = next(
            (
                item
                for item in existing
                if str(item.get("api_key") or "").strip() == str(entry.get("value") or "").strip()
            ),
            None,
        )
        if matching_existing is None and index - 1 < len(existing):
            matching_existing = existing[index - 1]
        output.append(
            {
                "id": str((matching_existing or {}).get("id") or uuid4().hex),
                "label": str((matching_existing or {}).get("label") or "").strip() or _default_provider_label(PROVIDER_GEMINI, index),
                "enabled": bool(entry.get("enabled", True)),
                "api_key": str(entry.get("value") or "").strip(),
            }
        )
    return output


def _normalize_settings_presets(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return [_build_default_preset()]

    presets: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        preset_id = str(item.get("id") or uuid4().hex)
        if preset_id in seen_ids:
            continue
        seen_ids.add(preset_id)
        preset_name = str(item.get("name") or f"Preset {index}").strip() or f"Preset {index}"
        preset_values = _normalize_preset_values(item.get("values"))
        presets.append(
            {
                "id": preset_id,
                "name": DEFAULT_PRESET_NAME if bool(item.get("locked")) else preset_name,
                "locked": _coerce_bool(item.get("locked", False), False),
                "values": preset_values,
            }
        )

    if not presets:
        presets.append(_build_default_preset())
    if not any(bool(preset.get("locked")) for preset in presets):
        presets[0]["locked"] = True
        presets[0]["name"] = DEFAULT_PRESET_NAME
    return presets


def _migrate_legacy_settings(raw: dict[str, Any]) -> dict[str, Any]:
    migrated = _default_raw_settings()

    for key in TOP_LEVEL_SETTINGS_KEYS:
        if key in raw:
            migrated[key] = _normalize_top_level_value(key, raw.get(key))

    for key in PROMPT_KEYS:
        if key in raw:
            migrated[key] = _normalize_top_level_value(key, raw.get(key))

    preset_values = _build_default_preset_values()
    preset_values["key_rotation_mode"] = str(raw.get("key_rotation_mode", preset_values["key_rotation_mode"]) or preset_values["key_rotation_mode"]).strip().upper()
    preset_values["ui_theme"] = str(raw.get("ui_theme", preset_values["ui_theme"]) or preset_values["ui_theme"]).strip()
    preset_values["graph_extraction_concurrency"] = raw.get(
        "graph_extraction_concurrency",
        raw.get("ingestion_concurrency", preset_values["graph_extraction_concurrency"]),
    )
    preset_values["graph_extraction_cooldown_seconds"] = raw.get(
        "graph_extraction_cooldown_seconds",
        preset_values["graph_extraction_cooldown_seconds"],
    )
    preset_values["embedding_concurrency"] = raw.get("embedding_concurrency", preset_values["embedding_concurrency"])
    preset_values["embedding_cooldown_seconds"] = raw.get(
        "embedding_cooldown_seconds",
        preset_values["embedding_cooldown_seconds"],
    )
    preset_values["slots"] = get_default_slot_configs()

    preset = _build_default_preset(name=DEFAULT_PRESET_NAME)
    preset["values"] = _normalize_preset_values(preset_values)
    migrated["settings_presets"] = [preset]
    migrated["active_settings_preset_id"] = preset["id"]

    provider_credentials = _normalize_provider_credentials_map(raw.get("provider_credentials"))
    if not provider_credentials.get(PROVIDER_GEMINI):
        provider_credentials[PROVIDER_GEMINI] = _build_legacy_provider_credentials_from_api_keys(raw.get("api_keys"))
    if raw.get("intenserp_base_url"):
        provider_credentials[PROVIDER_OPENAI_COMPATIBLE] = _normalize_provider_credential_entries(
            PROVIDER_OPENAI_COMPATIBLE,
            [
                *provider_credentials.get(PROVIDER_OPENAI_COMPATIBLE, []),
                {
                    "label": "Migrated Local Endpoint",
                    "enabled": True,
                    "api_base": raw.get("intenserp_base_url"),
                },
            ],
        )
    migrated["provider_credentials"] = provider_credentials
    return _normalize_raw_settings(migrated, is_migration_target=True)


def _normalize_raw_settings(raw: dict[str, Any], *, is_migration_target: bool = False) -> dict[str, Any]:
    normalized = _default_raw_settings()
    normalized["schema_version"] = SETTINGS_SCHEMA_VERSION

    for key in TOP_LEVEL_SETTINGS_KEYS:
        if key in raw:
            normalized[key] = _normalize_top_level_value(key, raw.get(key))

    for key in PROMPT_KEYS:
        if key in raw:
            normalized[key] = _normalize_top_level_value(key, raw.get(key))

    normalized["provider_credentials"] = _normalize_provider_credentials_map(raw.get("provider_credentials"))
    normalized["settings_presets"] = _normalize_settings_presets(raw.get("settings_presets"))

    active_id = str(raw.get("active_settings_preset_id") or "").strip()
    if not active_id or active_id not in {preset["id"] for preset in normalized["settings_presets"]}:
        active_id = normalized["settings_presets"][0]["id"]
    normalized["active_settings_preset_id"] = active_id

    if not is_migration_target and (
        raw.get("schema_version") != SETTINGS_SCHEMA_VERSION
        or "settings_presets" not in raw
        or "provider_credentials" not in raw
    ):
        return _migrate_legacy_settings(raw)

    return normalized


def _load_raw_settings() -> tuple[dict[str, Any], bool]:
    if not SETTINGS_FILE.exists():
        raw = _normalize_raw_settings({})
        return raw, True

    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (json.JSONDecodeError, OSError):
        loaded = {}
    if not isinstance(loaded, dict):
        loaded = {}

    normalized = _normalize_raw_settings(loaded)
    changed = loaded != normalized
    return normalized, changed


def _save_raw_settings(raw_settings: dict[str, Any]) -> None:
    dump_json_atomic(SETTINGS_FILE, raw_settings)


def _resolve_active_preset(raw_settings: dict[str, Any]) -> dict[str, Any]:
    active_id = str(raw_settings.get("active_settings_preset_id") or "")
    for preset in raw_settings.get("settings_presets", []):
        if str(preset.get("id")) == active_id:
            return preset
    return raw_settings["settings_presets"][0]


def resolve_slot_provider(settings: dict | None, slot: str) -> str:
    settings_data = dict(settings or load_settings())
    slots = settings_data.get("slots") if isinstance(settings_data.get("slots"), dict) else {}
    if slot in slots:
        return str(slots[slot].get("provider") or get_default_slot_configs()[slot]["provider"])
    return _build_slot_config_from_legacy(settings_data, slot)["provider"]


def get_provider_env_fallback(provider: str) -> dict[str, Any] | None:
    info = PROVIDER_REGISTRY.get(provider)
    if not info:
        return None

    env_entry: dict[str, Any] = {
        "id": f"env:{provider}",
        "label": f"{info.get('display_name', provider)} env",
        "enabled": True,
        "is_env_fallback": True,
    }
    found = False
    for field_name, env_vars in dict(info.get("env_field_vars") or {}).items():
        for env_var in env_vars:
            env_value = str(os.environ.get(env_var, "") or "").strip()
            if not env_value or env_value == "your_key_here":
                continue
            env_entry[field_name] = env_value.rstrip("/") if field_name in {"api_base", "base_url"} else env_value
            found = True
            break
    if not found and isinstance(info.get("default_entry"), dict):
        env_entry.update(dict(info["default_entry"]))
        found = True
    if found:
        return env_entry
    return None


def get_provider_credentials(provider: str, *, include_disabled: bool = True, include_env_fallback: bool = False) -> list[dict[str, Any]]:
    raw_settings, changed = _load_raw_settings()
    if changed:
        _save_raw_settings(raw_settings)

    entries = list(raw_settings.get("provider_credentials", {}).get(provider, []))
    if not include_disabled:
        entries = [entry for entry in entries if bool(entry.get("enabled", True))]

    if include_env_fallback:
        env_entry = get_provider_env_fallback(provider)
        if env_entry:
            entries = [*entries, env_entry]
    return entries


def get_provider_pool(provider: str) -> list[dict[str, Any]]:
    entries = get_provider_credentials(provider, include_disabled=False, include_env_fallback=True)
    required_fields = tuple(PROVIDER_REGISTRY.get(provider, {}).get("required_credential_fields", ()))
    pool: list[dict[str, Any]] = []
    for entry in entries:
        if all(str(entry.get(field) or "").strip() for field in required_fields):
            pool.append(entry)
    return pool


def get_enabled_api_keys(settings: dict | None = None) -> list[str]:
    """Return enabled Gemini API keys in persisted order."""
    if settings is None:
        return [str(entry.get("api_key")) for entry in get_provider_pool(PROVIDER_GEMINI)]

    provider_credentials = settings.get("_provider_credentials")
    if isinstance(provider_credentials, dict):
        entries = provider_credentials.get(PROVIDER_GEMINI, [])
        return [
            str(entry.get("api_key"))
            for entry in entries
            if bool(entry.get("enabled", True)) and str(entry.get("api_key") or "").strip()
        ]
    return [
        str(entry["value"])
        for entry in normalize_api_key_entries(settings.get("api_keys"))
        if bool(entry.get("enabled", True))
    ]


def _build_effective_settings(raw_settings: dict[str, Any]) -> dict[str, Any]:
    preset = _resolve_active_preset(raw_settings)
    effective = sanitize_settings(
        {
            **TOP_LEVEL_SETTINGS_DEFAULTS,
            **PRESET_SETTINGS_DEFAULTS,
            **{key: raw_settings.get(key) for key in TOP_LEVEL_SETTINGS_KEYS},
            **preset.get("values", {}),
            **{key: raw_settings.get(key) for key in PROMPT_KEYS},
        }
    )
    effective["_provider_credentials"] = raw_settings.get("provider_credentials", {})
    effective["_active_settings_preset_id"] = preset["id"]
    effective["_active_settings_preset_name"] = preset["name"]
    effective["_settings_presets"] = raw_settings.get("settings_presets", [])
    effective["_schema_version"] = raw_settings.get("schema_version", SETTINGS_SCHEMA_VERSION)
    effective["provider_status"] = compute_provider_statuses(effective)
    effective["provider_registry"] = get_provider_capabilities()
    effective["ai_catalog"] = build_ai_catalog()
    effective["settings_presets"] = [
        {"id": item["id"], "name": item["name"], "locked": bool(item.get("locked", False))}
        for item in raw_settings.get("settings_presets", [])
    ]
    effective["active_settings_preset_id"] = preset["id"]
    effective["active_settings_preset_name"] = preset["name"]
    effective["active_settings_preset_locked"] = bool(preset.get("locked", False))
    effective["provider_credentials_summary"] = {
        provider: {
            "stored": len(raw_settings.get("provider_credentials", {}).get(provider, [])),
            "enabled": sum(1 for entry in raw_settings.get("provider_credentials", {}).get(provider, []) if bool(entry.get("enabled", True))),
            "ready": len(get_provider_pool(provider)),
        }
        for provider in PROVIDER_REGISTRY
    }
    effective["api_keys"] = [
        {
            "value": str(entry.get("api_key") or ""),
            "enabled": bool(entry.get("enabled", True)),
        }
        for entry in raw_settings.get("provider_credentials", {}).get(PROVIDER_GEMINI, [])
        if str(entry.get("api_key") or "").strip()
    ]
    effective["disable_safety_filters"] = effective["gemini_disable_safety_filters"]
    return effective


def load_settings() -> dict:
    """Load the effective flat settings view used by the rest of the app."""
    with _SETTINGS_STATE_LOCK:
        raw_settings, changed = _load_raw_settings()
        if changed:
            _save_raw_settings(raw_settings)
        return _build_effective_settings(raw_settings)


def save_settings(settings: dict) -> None:
    """Persist flat configuration patches back into the active preset/top-level shape."""
    with _SETTINGS_STATE_LOCK:
        raw_settings, changed = _load_raw_settings()
        incoming = dict(settings or {})

        if "api_keys" in incoming:
            raw_settings["provider_credentials"][PROVIDER_GEMINI] = _build_legacy_provider_credentials_from_api_keys(
                incoming.get("api_keys"),
                existing_entries=raw_settings.get("provider_credentials", {}).get(PROVIDER_GEMINI, []),
            )
        if "provider_credentials" in incoming and isinstance(incoming["provider_credentials"], dict):
            raw_settings["provider_credentials"] = _normalize_provider_credentials_map(incoming["provider_credentials"])
        updated_top_level = {key: raw_settings.get(key) for key in TOP_LEVEL_SETTINGS_KEYS}
        for key in TOP_LEVEL_SETTINGS_KEYS:
            if key in incoming:
                updated_top_level[key] = _normalize_top_level_value(key, incoming.get(key))
        for key in PROMPT_KEYS:
            if key in incoming:
                raw_settings[key] = _normalize_top_level_value(key, incoming.get(key))
        raw_settings.update(updated_top_level)

        active_preset = _resolve_active_preset(raw_settings)
        preset_values = dict(active_preset.get("values", {}))
        preset_values = _apply_legacy_slot_aliases(preset_values)
        next_slots = dict(preset_values.get("slots") or {})
        if "slots" in incoming and isinstance(incoming["slots"], dict):
            for slot, slot_value in incoming["slots"].items():
                if slot in get_default_slot_configs():
                    next_slots[slot] = validate_slot_config(slot, slot_value)
        else:
            for slot in get_default_slot_configs():
                prefix = LEGACY_SLOT_KEY_TO_SETTING_PREFIX.get(slot)
                touched = False
                if slot == SLOT_EMBEDDING:
                    touched = any(key in incoming for key in ("embedding_provider", "embedding_model", "embedding_params"))
                elif prefix:
                    touched = any(
                        key in incoming
                        for key in (
                            prefix,
                            f"{prefix}_provider",
                            f"{prefix}_openai_compatible_provider",
                            f"{prefix}_groq_reasoning_effort",
                            f"{prefix}_thinking_level",
                            f"{prefix}_thinking_manual",
                        )
                    )
                if slot == SLOT_CHAT and any(key in incoming for key in ("chat_provider", "gemini_chat_send_thinking", "groq_chat_include_reasoning", "gemini_disable_safety_filters", "disable_safety_filters")):
                    touched = True
                if touched:
                    merged_source = {**preset_values, **incoming, "slots": next_slots}
                    next_slots[slot] = _build_slot_config_from_legacy(merged_source, slot)
        preset_values["slots"] = _normalize_slot_map(next_slots)
        for key in CONFIGURATION_PRESET_KEYS:
            if key == "slots":
                continue
            if key in incoming:
                preset_values[key] = incoming.get(key)
        active_preset["values"] = _normalize_preset_values(preset_values)

        _save_raw_settings(_normalize_raw_settings(raw_settings))


def create_settings_preset(name: str | None = None) -> dict[str, str]:
    with _SETTINGS_STATE_LOCK:
        raw_settings, changed = _load_raw_settings()
        active_preset = _resolve_active_preset(raw_settings)
        new_preset = {
            "id": uuid4().hex,
            "name": str(name or f"{active_preset['name']} Copy").strip() or f"{active_preset['name']} Copy",
            "locked": False,
            "values": dict(active_preset.get("values", {})),
        }
        raw_settings["settings_presets"].append(new_preset)
        raw_settings["active_settings_preset_id"] = new_preset["id"]
        _save_raw_settings(_normalize_raw_settings(raw_settings))
        return {"id": new_preset["id"], "name": new_preset["name"]}


def rename_settings_preset(preset_id: str, name: str) -> dict[str, str]:
    with _SETTINGS_STATE_LOCK:
        raw_settings, changed = _load_raw_settings()
        normalized_name = str(name or "").strip()
        if not normalized_name:
            raise ValueError("Preset name cannot be empty.")
        for preset in raw_settings["settings_presets"]:
            if str(preset.get("id")) == preset_id:
                if bool(preset.get("locked", False)):
                    raise ValueError("The default preset is locked and cannot be renamed.")
                preset["name"] = normalized_name
                _save_raw_settings(_normalize_raw_settings(raw_settings))
                return {"id": preset_id, "name": normalized_name}
        raise ValueError("Preset not found.")


def activate_settings_preset(preset_id: str) -> dict[str, str]:
    with _SETTINGS_STATE_LOCK:
        raw_settings, changed = _load_raw_settings()
        for preset in raw_settings["settings_presets"]:
            if str(preset.get("id")) == preset_id:
                raw_settings["active_settings_preset_id"] = preset_id
                _save_raw_settings(_normalize_raw_settings(raw_settings))
                return {"id": preset_id, "name": str(preset.get("name") or "")}
        raise ValueError("Preset not found.")


def get_text_model_option(provider: str, model_name: object) -> dict[str, Any] | None:
    normalized = str(model_name or "").strip().lower()
    if not normalized:
        return None
    for option in build_ai_catalog()["providers"].get(provider, {}).get("models", {}).get(TASK_CHAT, []):
        if str(option.get("value") or "").strip().lower() == normalized:
            return dict(option)
    return None


def get_embedding_model_option(provider: str, model_name: object) -> dict[str, Any] | None:
    normalized = str(model_name or "").strip().lower()
    if not normalized:
        return None
    for option in build_ai_catalog()["providers"].get(provider, {}).get("models", {}).get(TASK_EMBEDDING, []):
        if str(option.get("value") or "").strip().lower() == normalized:
            return dict(option)
    return None


def get_provider_capabilities() -> dict[str, Any]:
    catalog = build_ai_catalog()
    sorted_providers = sorted(
        catalog["providers"].items(),
        key=lambda item: str(item[1].get("display_name") or item[0]).lower(),
    )
    return {
        "providers": {
            provider: {
                "id": provider,
                "display_name": entry["display_name"],
                "family": provider,
                "supported_slots": list(entry.get("supported_slots", [])),
                "required_credential_fields": list(entry.get("required_credential_fields", [])),
                "credential_fields": list(entry.get("credential_fields", [])),
                "supports_embedding": provider_supports_embeddings(provider),
                "supports_gemini_safety": provider == PROVIDER_GEMINI,
                "supports_gemini_thinking": provider == PROVIDER_GEMINI,
                "supports_groq_reasoning": provider == PROVIDER_GROQ,
                "custom_model_first": bool(entry.get("custom_model_first")),
                "selectable": bool(entry.get("selectable", True)),
                "placeholder_models": dict(entry.get("placeholder_models", {})),
                "text_model_options": list(entry.get("models", {}).get(TASK_CHAT, [])),
                "embedding_model_options": list(entry.get("models", {}).get(TASK_EMBEDDING, [])),
            }
            for provider, entry in sorted_providers
        },
        "families": {
            slot: {
                "default": get_default_slot_configs()[slot]["provider"],
                "options": sorted(
                    [
                        {
                            "value": provider,
                            "label": catalog["providers"][provider]["display_name"],
                        }
                        for provider, _entry in sorted_providers
                        if provider_is_selectable(provider)
                        if slot in catalog["providers"][provider]["supported_slots"]
                    ],
                    key=lambda item: str(item.get("label") or item.get("value") or "").lower(),
                ),
            }
            for slot in get_default_slot_configs()
        },
        "openai_compatible_providers": [],
    }


def _build_missing_credential_message(provider: str, slot: str) -> str:
    provider_name = str(PROVIDER_REGISTRY.get(provider, {}).get("display_name") or provider)
    required = PROVIDER_REGISTRY.get(provider, {}).get("required_credential_fields", ())
    if required == ("api_key",):
        return f"{provider_name} is selected for {slot}, but no enabled API key is ready in Key Library."
    if required == ("api_base",) or required == ("base_url",):
        return f"{provider_name} is selected for {slot}, but no enabled base URL is ready in Key Library."
    if not required:
        return f"{provider_name} requires local authentication or a default local endpoint before this slot can run."
    joined = ", ".join(str(field) for field in required)
    return f"{provider_name} is selected for {slot}, but the Key Library is missing required fields: {joined}."


def compute_provider_statuses(settings: dict | None = None) -> dict[str, dict[str, Any]]:
    settings_data = settings or load_settings()
    statuses: dict[str, dict[str, Any]] = {}
    for slot in (SLOT_FLASH, SLOT_CHAT, SLOT_ENTITY_CHOOSER, SLOT_ENTITY_COMBINER, SLOT_EMBEDDING):
        provider = resolve_slot_provider(settings_data, slot)
        provider_info = PROVIDER_REGISTRY.get(provider, {})
        slot_label = slot.replace("_", " ")
        ok = True
        message = ""

        if slot not in provider_info.get("supported_slots", set()):
            ok = False
            message = f"{provider_info.get('display_name', provider)} does not support the {slot_label} slot."
        elif slot == SLOT_EMBEDDING and not provider_supports_embeddings(provider):
            ok = False
            message = f"{provider_info.get('display_name', provider)} is not available for embeddings yet."
        elif provider_info.get("required_credential_fields") and not get_provider_pool(provider):
            ok = False
            message = _build_missing_credential_message(provider, slot_label)

        statuses[slot] = {
            "slot": slot,
            "provider": provider,
            "provider_family": provider,
            "ok": ok,
            "severity": "ok" if ok else "error",
            "message": message,
            "supports_gemini_safety": provider == PROVIDER_GEMINI,
            "supports_gemini_thinking": provider == PROVIDER_GEMINI,
            "supports_groq_reasoning": provider == PROVIDER_GROQ,
        }
    return statuses


def get_provider_library_payload(provider: str) -> dict[str, Any]:
    if provider not in PROVIDER_REGISTRY:
        raise ValueError("Unknown provider.")
    entries = get_provider_credentials(provider, include_disabled=True, include_env_fallback=False)
    info = PROVIDER_REGISTRY[provider]
    payload_entries = []
    required_fields = tuple(info.get("required_credential_fields", ()))
    for entry in entries:
        payload_entry = {
            "id": str(entry.get("id") or ""),
            "label": str(entry.get("label") or ""),
            "enabled": bool(entry.get("enabled", True)),
            "required_ready": all(str(entry.get(field) or "").strip() for field in required_fields),
        }
        for field in info.get("credential_fields", ()):
            field_name = field["name"]
            raw_value = str(entry.get(field_name) or "")
            if field.get("secret"):
                payload_entry[f"{field_name}_masked"] = _mask_secret(raw_value)
                payload_entry[f"has_{field_name}"] = bool(raw_value)
            else:
                payload_entry[field_name] = raw_value
        payload_entries.append(payload_entry)

    env_fallback = get_provider_env_fallback(provider)
    payload_env_fallback = None
    if env_fallback:
        payload_env_fallback = {"label": str(env_fallback.get("label") or ""), "enabled": True}
        for field in info.get("credential_fields", ()):
            field_name = field["name"]
            raw_value = str(env_fallback.get(field_name) or "")
            if field.get("secret"):
                payload_env_fallback[f"{field_name}_masked"] = _mask_secret(raw_value)
                payload_env_fallback[f"has_{field_name}"] = bool(raw_value)
            else:
                payload_env_fallback[field_name] = raw_value

    return {
        "provider": provider,
        "display_name": info.get("display_name"),
        "credential_fields": list(info.get("credential_fields", ())),
        "entries": payload_entries,
        "env_fallback": payload_env_fallback,
    }


def upsert_provider_credential(provider: str, payload: dict[str, Any]) -> dict[str, Any]:
    if provider not in PROVIDER_REGISTRY:
        raise ValueError("Unknown provider.")

    with _SETTINGS_STATE_LOCK:
        raw_settings, changed = _load_raw_settings()
        entries = list(raw_settings["provider_credentials"].get(provider, []))
        normalized_payload = dict(payload or {})
        if normalized_payload.get("base_url") and not normalized_payload.get("api_base"):
            normalized_payload["api_base"] = normalized_payload.get("base_url")
        entry_id = str(normalized_payload.get("id") or uuid4().hex)
        updated_entry = {
            "id": entry_id,
            "label": str(normalized_payload.get("label") or "").strip() or _default_provider_label(provider, len(entries) + 1),
            "enabled": _coerce_bool(normalized_payload.get("enabled", True), True),
        }
        for field in PROVIDER_REGISTRY[provider].get("credential_fields", ()):
            field_name = field["name"]
            raw_value = normalized_payload.get(field_name)
            if raw_value is None:
                existing = next((item for item in entries if str(item.get("id")) == entry_id), None)
                if existing and field_name in existing:
                    updated_entry[field_name] = existing[field_name]
                continue
            updated_entry[field_name] = str(raw_value).strip()

        replaced = False
        for index, entry in enumerate(entries):
            if str(entry.get("id")) == entry_id:
                entries[index] = updated_entry
                replaced = True
                break
        if not replaced:
            entries.append(updated_entry)

        raw_settings["provider_credentials"][provider] = _normalize_provider_credential_entries(provider, entries)
        _save_raw_settings(_normalize_raw_settings(raw_settings))
        return get_provider_library_payload(provider)


def remove_provider_credential(provider: str, credential_id: str) -> dict[str, Any]:
    if provider not in PROVIDER_REGISTRY:
        raise ValueError("Unknown provider.")
    with _SETTINGS_STATE_LOCK:
        raw_settings, changed = _load_raw_settings()
        entries = [
            entry
            for entry in raw_settings["provider_credentials"].get(provider, [])
            if str(entry.get("id")) != credential_id
        ]
        raw_settings["provider_credentials"][provider] = entries
        _save_raw_settings(_normalize_raw_settings(raw_settings))
        return get_provider_library_payload(provider)


def update_provider_credential_enabled(provider: str, credential_id: str, enabled: bool) -> dict[str, Any]:
    if provider not in PROVIDER_REGISTRY:
        raise ValueError("Unknown provider.")
    with _SETTINGS_STATE_LOCK:
        raw_settings, changed = _load_raw_settings()
        for entry in raw_settings["provider_credentials"].get(provider, []):
            if str(entry.get("id")) == credential_id:
                entry["enabled"] = bool(enabled)
                break
        _save_raw_settings(_normalize_raw_settings(raw_settings))
        return get_provider_library_payload(provider)


def load_default_prompts() -> dict:
    """Load the read-only default prompts file."""
    with open(DEFAULT_PROMPTS_FILE, "r", encoding="utf-8") as handle:
        return json.load(handle)


def get_supported_gemini_thinking_levels(model_name: object) -> list[str]:
    option = get_text_model_option(PROVIDER_GEMINI, model_name)
    if not option:
        return []
    supported_params = {str(item) for item in option.get("supported_params", [])}
    if "thinking" in supported_params or "reasoning_effort" in supported_params:
        return ["low", "medium", "high", "xhigh"]
    return []


def get_supported_groq_reasoning_options(model_name: object) -> list[str]:
    option = get_text_model_option(PROVIDER_GROQ, model_name)
    if not option:
        return []
    supported_params = {str(item) for item in option.get("supported_params", [])}
    if "reasoning_effort" not in supported_params:
        return []
    return ["low", "medium", "high", "xhigh", "none"]


def _slot_name_from_legacy_key(slot_key: str) -> str | None:
    reverse = {value: key for key, value in LEGACY_SLOT_KEY_TO_SETTING_PREFIX.items()}
    return reverse.get(slot_key)


def resolve_groq_reasoning_effort(
    settings: dict,
    *,
    slot_key: str,
    model_name: object,
) -> str:
    slot_name = _slot_name_from_legacy_key(slot_key)
    if slot_name and isinstance(settings.get("slots"), dict):
        params = settings["slots"].get(slot_name, {}).get("params") or {}
        raw_value = str(params.get("reasoning_effort") or "").strip().lower()
    else:
        raw_value = str(settings.get(f"{slot_key}_groq_reasoning_effort", "") or "").strip().lower()
    if not raw_value:
        return ""

    option = get_text_model_option(PROVIDER_GROQ, model_name)
    if option is None:
        return raw_value

    supported_options = get_supported_groq_reasoning_options(model_name)
    if not supported_options:
        return ""

    return raw_value if raw_value in supported_options else ""


def resolve_gemini_thinking_settings(
    settings: dict,
    *,
    slot_key: str,
    model_name: object,
    include_thoughts: bool = False,
) -> dict | None:
    slot_name = _slot_name_from_legacy_key(slot_key)
    if slot_name and isinstance(settings.get("slots"), dict):
        params = dict(settings["slots"].get(slot_name, {}).get("params") or {})
        payload: dict[str, object] = {}
        thinking = params.get("thinking")
        if isinstance(thinking, dict):
            payload.update(thinking)
        reasoning_effort = str(params.get("reasoning_effort") or "").strip()
        if reasoning_effort:
            payload.setdefault("thinking_level", reasoning_effort.upper())
        if include_thoughts:
            payload["include_thoughts"] = True
        return payload or None

    payload: dict[str, object] = {}
    supported_levels = get_supported_gemini_thinking_levels(model_name)

    if supported_levels:
        level_key = f"{slot_key}_thinking_level"
        raw_level = str(settings.get(level_key, "") or "").strip().lower()
        if raw_level and raw_level in supported_levels:
            payload["thinking_level"] = raw_level.upper()
    else:
        manual_key = f"{slot_key}_thinking_manual"
        raw_manual = str(settings.get(manual_key, "") or "").strip()
        if raw_manual:
            try:
                payload["thinking_budget"] = int(raw_manual)
            except ValueError:
                payload["thinking_level"] = raw_manual.upper()

    if include_thoughts:
        payload["include_thoughts"] = True

    return payload or None


def get_prompt_value_with_source(
    key: str,
    *,
    world_id: str | None = None,
    meta: dict | None = None,
    settings: dict | None = None,
    defaults: dict | None = None,
) -> tuple[str, str]:
    settings_data = settings or load_settings()
    defaults_data = defaults or load_default_prompts()
    meta_data = meta if meta is not None else (load_world_meta(world_id) if world_id else None)

    if key in WORLD_INGEST_PROMPT_KEYS:
        world_overrides = get_world_ingest_prompt_overrides(meta=meta_data)
        world_value = world_overrides.get(key)
        if world_value:
            return world_value, "world"

    global_value = settings_data.get(key)
    if global_value:
        return str(global_value), "global"

    if key not in defaults_data:
        raise ValueError(f"Prompt key '{key}' not found in settings or default_prompts.json")
    return str(defaults_data[key]), "default"


def load_prompt(key: str, *, world_id: str | None = None, meta: dict | None = None) -> str:
    value, _ = get_prompt_value_with_source(key, world_id=world_id, meta=meta)
    return value


def world_dir(world_id: str) -> Path:
    return SAVED_WORLDS_DIR / world_id


def world_meta_path(world_id: str) -> Path:
    return world_dir(world_id) / "meta.json"


def load_world_meta(world_id: str) -> dict | None:
    path = world_meta_path(world_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return None


def get_default_ingest_settings(settings: dict | None = None) -> dict:
    settings_data = settings or load_settings()
    embedding_slot = dict((settings_data.get("slots") or {}).get(SLOT_EMBEDDING) or get_default_slot_configs()[SLOT_EMBEDDING])
    return {
        "chunk_size_chars": int(settings_data.get("chunk_size_chars", TOP_LEVEL_SETTINGS_DEFAULTS["chunk_size_chars"])),
        "chunk_overlap_chars": int(settings_data.get("chunk_overlap_chars", TOP_LEVEL_SETTINGS_DEFAULTS["chunk_overlap_chars"])),
        "embedding_provider": str(embedding_slot.get("provider") or get_default_slot_configs()[SLOT_EMBEDDING]["provider"]),
        "embedding_openai_compatible_provider": str(embedding_slot.get("provider") or get_default_slot_configs()[SLOT_EMBEDDING]["provider"]),
        "embedding_model": str(embedding_slot.get("model") or get_default_slot_configs()[SLOT_EMBEDDING]["model"]),
        "embedding_params": dict(embedding_slot.get("params") or {}),
        "glean_amount": _coerce_int(
            settings_data.get("glean_amount", TOP_LEVEL_SETTINGS_DEFAULTS["glean_amount"]),
            TOP_LEVEL_SETTINGS_DEFAULTS["glean_amount"],
            minimum=0,
        ),
        "locked_at": None,
        "last_ingest_settings_at": None,
    }


def get_world_ingest_settings(*, world_id: str | None = None, meta: dict | None = None) -> dict:
    meta_data = meta if meta is not None else (load_world_meta(world_id) if world_id else None)
    defaults = get_default_ingest_settings()
    stored = {}
    if meta_data:
        raw = meta_data.get("ingest_settings")
        if isinstance(raw, dict):
            stored = raw
        legacy_embedding = meta_data.get("embedding_model")
        legacy_embedding_provider = meta_data.get("embedding_provider")
        legacy_world_has_locked_context = bool(
            stored.get("locked_at")
            or stored.get("last_ingest_settings_at")
            or meta_data.get("total_chunks")
            or meta_data.get("ingestion_status") not in {"pending", None}
        )
        if legacy_embedding and legacy_world_has_locked_context and not stored.get("embedding_model"):
            stored = {**stored, "embedding_model": legacy_embedding}
        if legacy_embedding_provider and legacy_world_has_locked_context and not stored.get("embedding_provider"):
            stored = {**stored, "embedding_provider": legacy_embedding_provider}

    output = dict(defaults)
    for key in INGEST_SETTINGS_KEYS:
        value = stored.get(key)
        if value in (None, ""):
            continue
        if key in {"chunk_size_chars", "chunk_overlap_chars", "glean_amount"}:
            try:
                output[key] = int(value)
            except (TypeError, ValueError):
                continue
        elif key == "embedding_params":
            if isinstance(value, dict):
                output[key] = dict(value)
        else:
            output[key] = str(value)

    output["embedding_provider"] = _normalize_provider_family(SLOT_EMBEDDING, output.get("embedding_provider"))
    output["embedding_openai_compatible_provider"] = output["embedding_provider"]
    output["embedding_params"] = dict(output.get("embedding_params") or {})

    locked_at = stored.get("locked_at")
    if locked_at:
        output["locked_at"] = str(locked_at)
    last_ingest_settings_at = stored.get("last_ingest_settings_at")
    if last_ingest_settings_at:
        output["last_ingest_settings_at"] = str(last_ingest_settings_at)
    return output


def get_world_embedding_provider(world_id: str) -> str:
    ingest_settings = get_world_ingest_settings(world_id=world_id)
    return str(ingest_settings.get("embedding_provider") or get_default_slot_configs()[SLOT_EMBEDDING]["provider"])


def get_world_embedding_model(world_id: str) -> str:
    return get_world_ingest_settings(world_id=world_id)["embedding_model"]


def set_world_ingest_settings(
    world_id: str,
    ingest_settings: dict,
    *,
    lock: bool = False,
    touch: bool = True,
) -> dict | None:
    path = world_meta_path(world_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            meta = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return None

    current = get_world_ingest_settings(meta=meta)
    updated = dict(current)
    for key in INGEST_SETTINGS_KEYS:
        value = ingest_settings.get(key)
        if value in (None, ""):
            continue
        if key in {"chunk_size_chars", "chunk_overlap_chars", "glean_amount"}:
            try:
                updated[key] = int(value)
            except (TypeError, ValueError):
                continue
        elif key == "embedding_params":
            if isinstance(value, dict):
                updated[key] = dict(value)
        else:
            updated[key] = str(value)

    updated["embedding_provider"] = _normalize_provider_family(SLOT_EMBEDDING, updated.get("embedding_provider"))
    updated["embedding_openai_compatible_provider"] = updated["embedding_provider"]
    updated["embedding_params"] = dict(updated.get("embedding_params") or {})

    now = _now_iso()
    updated["locked_at"] = updated.get("locked_at") or (now if lock else None)
    if touch:
        updated["last_ingest_settings_at"] = now

    meta["ingest_settings"] = updated
    meta["embedding_model"] = updated["embedding_model"]
    meta["embedding_provider"] = updated["embedding_provider"]

    dump_json_atomic(path, meta)
    return updated


def set_world_embedding_model(world_id: str, embedding_model: str) -> None:
    set_world_ingest_settings(world_id, {"embedding_model": embedding_model}, lock=False, touch=False)


def get_world_ingest_prompt_overrides(*, world_id: str | None = None, meta: dict | None = None) -> dict[str, str]:
    meta_data = meta if meta is not None else (load_world_meta(world_id) if world_id else None)
    if not isinstance(meta_data, dict):
        return {}
    raw = meta_data.get("ingest_prompt_overrides")
    if not isinstance(raw, dict):
        return {}

    output: dict[str, str] = {}
    for key in WORLD_INGEST_PROMPT_KEYS:
        value = raw.get(key)
        if not isinstance(value, str):
            continue
        if value.strip():
            output[key] = value
    return output


def set_world_ingest_prompt_overrides(world_id: str, prompt_overrides: dict | None) -> dict[str, str] | None:
    path = world_meta_path(world_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            meta = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return None

    normalized: dict[str, str] = {}
    for key in WORLD_INGEST_PROMPT_KEYS:
        value = prompt_overrides.get(key) if isinstance(prompt_overrides, dict) else None
        if not isinstance(value, str):
            continue
        if value.strip():
            normalized[key] = value

    meta["ingest_prompt_overrides"] = normalized
    dump_json_atomic(path, meta)
    return normalized


def get_world_ingest_prompt_states(*, world_id: str | None = None, meta: dict | None = None) -> dict[str, dict[str, str]]:
    settings_data = load_settings()
    defaults_data = load_default_prompts()
    meta_data = meta if meta is not None else (load_world_meta(world_id) if world_id else None)
    result: dict[str, dict[str, str]] = {}
    for key in WORLD_INGEST_PROMPT_KEYS:
        value, source = get_prompt_value_with_source(
            key,
            world_id=world_id,
            meta=meta_data,
            settings=settings_data,
            defaults=defaults_data,
        )
        result[key] = {"value": value, "source": source}
    return result


def world_graph_path(world_id: str) -> Path:
    return world_dir(world_id) / "world_graph.gexf"


def world_checkpoint_path(world_id: str) -> Path:
    return world_dir(world_id) / "checkpoint.json"


def world_log_path(world_id: str) -> Path:
    return world_dir(world_id) / "ingestion_log.json"


def world_safety_reviews_path(world_id: str) -> Path:
    return world_dir(world_id) / "ingestion_safety_reviews.json"


def world_sources_dir(world_id: str) -> Path:
    directory = world_dir(world_id) / "sources"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def world_chroma_dir(world_id: str) -> Path:
    directory = world_dir(world_id) / "chroma"
    directory.mkdir(parents=True, exist_ok=True)
    return directory
