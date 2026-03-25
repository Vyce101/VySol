"""App-wide constants, provider capabilities, and settings I/O."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .atomic_json import dump_json_atomic

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
SETTINGS_DIR = ROOT_DIR / "settings"
SAVED_WORLDS_DIR = ROOT_DIR / "saved_worlds"

SETTINGS_FILE = SETTINGS_DIR / "settings.json"
DEFAULT_PROMPTS_FILE = SETTINGS_DIR / "default_prompts.json"

SAVED_WORLDS_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_DIR.mkdir(parents=True, exist_ok=True)

SETTINGS_SCHEMA_VERSION = 2
DEFAULT_PRESET_NAME = "Default"

PROVIDER_GEMINI = "gemini"
PROVIDER_GROQ = "groq"
PROVIDER_INTENSERP = "intenserp"

SLOT_FLASH = "flash"
SLOT_CHAT = "chat"
SLOT_ENTITY_CHOOSER = "entity_chooser"
SLOT_ENTITY_COMBINER = "entity_combiner"
SLOT_EMBEDDING = "embedding"

PROVIDER_REGISTRY: dict[str, dict[str, Any]] = {
    PROVIDER_GEMINI: {
        "family": PROVIDER_GEMINI,
        "display_name": "Google (Gemini)",
        "supported_slots": {SLOT_FLASH, SLOT_CHAT, SLOT_ENTITY_CHOOSER, SLOT_ENTITY_COMBINER, SLOT_EMBEDDING},
        "required_credential_fields": ("api_key",),
        "credential_fields": (
            {"name": "api_key", "label": "API Key", "secret": True, "multiline": False},
        ),
        "supports_embedding": True,
        "supports_gemini_safety": True,
        "supports_gemini_thinking": True,
        "supports_groq_reasoning": False,
        "env_api_key_vars": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    },
    PROVIDER_GROQ: {
        "family": "openai_compatible",
        "display_name": "Groq",
        "supported_slots": {SLOT_FLASH, SLOT_CHAT, SLOT_ENTITY_CHOOSER, SLOT_ENTITY_COMBINER, SLOT_EMBEDDING},
        "required_credential_fields": ("api_key",),
        "credential_fields": (
            {"name": "api_key", "label": "API Key", "secret": True, "multiline": False},
        ),
        "supports_embedding": False,
        "supports_gemini_safety": False,
        "supports_gemini_thinking": False,
        "supports_groq_reasoning": True,
        "env_api_key_vars": ("GROQ_API_KEY",),
        "default_base_url": "https://api.groq.com/openai/v1",
    },
    PROVIDER_INTENSERP: {
        "family": PROVIDER_INTENSERP,
        "display_name": "IntenseRP Next",
        "supported_slots": {SLOT_CHAT},
        "required_credential_fields": ("base_url",),
        "credential_fields": (
            {"name": "base_url", "label": "Base URL", "secret": False, "multiline": False},
        ),
        "supports_embedding": False,
        "supports_gemini_safety": False,
        "supports_gemini_thinking": False,
        "supports_groq_reasoning": False,
        "env_base_url_vars": ("INTENSERP_BASE_URL",),
        "default_base_url": "http://127.0.0.1:7777/v1",
    },
}

OPENAI_COMPATIBLE_PROVIDERS = (PROVIDER_GROQ,)
PROVIDER_FAMILY_OPTIONS: dict[str, dict[str, Any]] = {
    SLOT_FLASH: {
        "default": PROVIDER_GEMINI,
        "options": (
            {"value": PROVIDER_GEMINI, "label": "Google (Gemini)"},
            {"value": "openai_compatible", "label": "OpenAI-compatible"},
        ),
    },
    SLOT_CHAT: {
        "default": PROVIDER_GEMINI,
        "options": (
            {"value": PROVIDER_GEMINI, "label": "Google (Gemini)"},
            {"value": "openai_compatible", "label": "OpenAI-compatible"},
            {"value": PROVIDER_INTENSERP, "label": "IntenseRP Next"},
        ),
    },
    SLOT_ENTITY_CHOOSER: {
        "default": PROVIDER_GEMINI,
        "options": (
            {"value": PROVIDER_GEMINI, "label": "Google (Gemini)"},
            {"value": "openai_compatible", "label": "OpenAI-compatible"},
        ),
    },
    SLOT_ENTITY_COMBINER: {
        "default": PROVIDER_GEMINI,
        "options": (
            {"value": PROVIDER_GEMINI, "label": "Google (Gemini)"},
            {"value": "openai_compatible", "label": "OpenAI-compatible"},
        ),
    },
    SLOT_EMBEDDING: {
        "default": PROVIDER_GEMINI,
        "options": (
            {"value": PROVIDER_GEMINI, "label": "Google (Gemini)"},
            {"value": "openai_compatible", "label": "OpenAI-compatible"},
        ),
    },
}

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
    "default_model_flash": "gemini-3.1-flash-lite-preview",
    "default_model_flash_provider": PROVIDER_GEMINI,
    "default_model_flash_openai_compatible_provider": PROVIDER_GROQ,
    "default_model_flash_thinking_level": "minimal",
    "default_model_flash_thinking_manual": "",
    "default_model_flash_groq_reasoning_effort": "",
    "default_model_chat": "gemini-3-flash-preview",
    "default_model_chat_provider": PROVIDER_GEMINI,
    "default_model_chat_openai_compatible_provider": PROVIDER_GROQ,
    "default_model_chat_thinking_level": "high",
    "default_model_chat_thinking_manual": "",
    "default_model_chat_groq_reasoning_effort": "",
    "default_model_entity_chooser": "gemini-3.1-flash-lite-preview",
    "default_model_entity_chooser_provider": PROVIDER_GEMINI,
    "default_model_entity_chooser_openai_compatible_provider": PROVIDER_GROQ,
    "default_model_entity_chooser_thinking_level": "high",
    "default_model_entity_chooser_thinking_manual": "",
    "default_model_entity_chooser_groq_reasoning_effort": "",
    "default_model_entity_combiner": "gemini-3.1-flash-lite-preview",
    "default_model_entity_combiner_provider": PROVIDER_GEMINI,
    "default_model_entity_combiner_openai_compatible_provider": PROVIDER_GROQ,
    "default_model_entity_combiner_thinking_level": "high",
    "default_model_entity_combiner_thinking_manual": "",
    "default_model_entity_combiner_groq_reasoning_effort": "",
    "embedding_provider": PROVIDER_GEMINI,
    "embedding_openai_compatible_provider": PROVIDER_GROQ,
    "embedding_model": "gemini-embedding-2-preview",
    "ui_theme": "dark",
    "graph_extraction_concurrency": 4,
    "graph_extraction_cooldown_seconds": 0.0,
    "embedding_concurrency": 8,
    "embedding_cooldown_seconds": 0.0,
    "gemini_disable_safety_filters": False,
    "gemini_chat_send_thinking": True,
    "groq_chat_include_reasoning": False,
    "intenserp_model_id": "glm-chat",
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
    "embedding_openai_compatible_provider",
    "embedding_model",
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

TEXT_MODEL_OPTIONS_BY_PROVIDER: dict[str, tuple[dict[str, Any], ...]] = {
    PROVIDER_GEMINI: (
        {
            "value": "gemini-3.1-pro-preview",
            "label": "Gemini 3.1 Pro Preview",
            "gemini_thinking_levels": ("low", "medium", "high"),
        },
        {
            "value": "gemini-3.1-flash-lite-preview",
            "label": "Gemini 3.1 Flash-Lite Preview",
            "gemini_thinking_levels": ("minimal", "low", "medium", "high"),
        },
        {
            "value": "gemini-3-flash-preview",
            "label": "Gemini 3 Flash Preview",
            "gemini_thinking_levels": ("minimal", "low", "medium", "high"),
        },
    ),
    PROVIDER_GROQ: (
        {
            "value": "openai/gpt-oss-20b",
            "label": "OpenAI GPT-OSS 20B",
            "groq_reasoning_options": (
                {"value": "low", "label": "Low"},
                {"value": "medium", "label": "Medium"},
                {"value": "high", "label": "High"},
            ),
        },
        {
            "value": "openai/gpt-oss-120b",
            "label": "OpenAI GPT-OSS 120B",
            "groq_reasoning_options": (
                {"value": "low", "label": "Low"},
                {"value": "medium", "label": "Medium"},
                {"value": "high", "label": "High"},
            ),
        },
        {
            "value": "qwen/qwen3-32b",
            "label": "Qwen 3 32B",
            "groq_reasoning_options": (
                {"value": "none", "label": "None"},
                {"value": "default", "label": "Reasoning On (provider default)"},
            ),
        },
        {
            "value": "llama-3.3-70b-versatile",
            "label": "Llama 3.3 70B Versatile",
        },
        {
            "value": "llama-3.1-8b-instant",
            "label": "Llama 3.1 8B Instant",
        },
        {
            "value": "moonshotai/kimi-k2-instruct-0905",
            "label": "MoonshotAI Kimi K2 Instruct 0905",
        },
    ),
}

EMBEDDING_MODEL_OPTIONS_BY_PROVIDER: dict[str, tuple[dict[str, str], ...]] = {
    PROVIDER_GEMINI: (
        {"value": "gemini-embedding-001", "label": "Gemini Embedding 001"},
        {"value": "gemini-embedding-2-preview", "label": "Gemini Embedding 2 Preview"},
    ),
    PROVIDER_GROQ: (),
    PROVIDER_INTENSERP: (),
}

_SLOT_PROVIDER_FIELDS = {
    SLOT_FLASH: ("default_model_flash_provider", "default_model_flash_openai_compatible_provider"),
    SLOT_CHAT: ("default_model_chat_provider", "default_model_chat_openai_compatible_provider"),
    SLOT_ENTITY_CHOOSER: ("default_model_entity_chooser_provider", "default_model_entity_chooser_openai_compatible_provider"),
    SLOT_ENTITY_COMBINER: ("default_model_entity_combiner_provider", "default_model_entity_combiner_openai_compatible_provider"),
    SLOT_EMBEDDING: ("embedding_provider", "embedding_openai_compatible_provider"),
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
    allowed = {item["value"] for item in PROVIDER_FAMILY_OPTIONS.get(slot, {}).get("options", ())}
    if normalized in allowed:
        return normalized
    if slot == SLOT_CHAT and normalized == PROVIDER_GROQ:
        return "openai_compatible"
    return str(PROVIDER_FAMILY_OPTIONS.get(slot, {}).get("default", PROVIDER_GEMINI))


def _normalize_openai_compatible_provider(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in OPENAI_COMPATIBLE_PROVIDERS:
        return normalized
    return PROVIDER_GROQ


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


def _normalize_preset_values(value: object) -> dict[str, Any]:
    incoming = value if isinstance(value, dict) else {}
    normalized = dict(PRESET_SETTINGS_DEFAULTS)
    for key in CONFIGURATION_PRESET_KEYS:
        if key in incoming:
            normalized[key] = incoming[key]

    normalized["key_rotation_mode"] = (
        "ROUND_ROBIN" if str(normalized.get("key_rotation_mode", "")).strip().upper() == "ROUND_ROBIN" else "FAIL_OVER"
    )
    normalized["ui_theme"] = (
        "light" if str(normalized.get("ui_theme", PRESET_SETTINGS_DEFAULTS["ui_theme"])).strip().lower() == "light" else "dark"
    )
    normalized["graph_extraction_concurrency"] = _coerce_int(
        normalized.get("graph_extraction_concurrency"),
        PRESET_SETTINGS_DEFAULTS["graph_extraction_concurrency"],
        minimum=1,
    )
    normalized["graph_extraction_cooldown_seconds"] = _coerce_float(
        normalized.get("graph_extraction_cooldown_seconds"),
        PRESET_SETTINGS_DEFAULTS["graph_extraction_cooldown_seconds"],
        minimum=0.0,
    )
    normalized["embedding_concurrency"] = _coerce_int(
        normalized.get("embedding_concurrency"),
        PRESET_SETTINGS_DEFAULTS["embedding_concurrency"],
        minimum=1,
    )
    normalized["embedding_cooldown_seconds"] = _coerce_float(
        normalized.get("embedding_cooldown_seconds"),
        PRESET_SETTINGS_DEFAULTS["embedding_cooldown_seconds"],
        minimum=0.0,
    )
    normalized["gemini_disable_safety_filters"] = _coerce_bool(
        normalized.get("gemini_disable_safety_filters"),
        PRESET_SETTINGS_DEFAULTS["gemini_disable_safety_filters"],
    )
    normalized["gemini_chat_send_thinking"] = _coerce_bool(
        normalized.get("gemini_chat_send_thinking"),
        PRESET_SETTINGS_DEFAULTS["gemini_chat_send_thinking"],
    )
    normalized["groq_chat_include_reasoning"] = _coerce_bool(
        normalized.get("groq_chat_include_reasoning"),
        PRESET_SETTINGS_DEFAULTS["groq_chat_include_reasoning"],
    )
    for slot in _SLOT_PROVIDER_FIELDS:
        provider_field, openai_provider_field = _SLOT_PROVIDER_FIELDS[slot]
        normalized[provider_field] = _normalize_provider_family(slot, normalized.get(provider_field))
        normalized[openai_provider_field] = _normalize_openai_compatible_provider(normalized.get(openai_provider_field))

    thinking_string_keys = (
        "default_model_flash_thinking_level",
        "default_model_flash_thinking_manual",
        "default_model_flash_groq_reasoning_effort",
        "default_model_chat_thinking_level",
        "default_model_chat_thinking_manual",
        "default_model_chat_groq_reasoning_effort",
        "default_model_entity_chooser_thinking_level",
        "default_model_entity_chooser_thinking_manual",
        "default_model_entity_chooser_groq_reasoning_effort",
        "default_model_entity_combiner_thinking_level",
        "default_model_entity_combiner_thinking_manual",
        "default_model_entity_combiner_groq_reasoning_effort",
    )
    for key in thinking_string_keys:
        normalized[key] = str(normalized.get(key, PRESET_SETTINGS_DEFAULTS[key]) or "").strip()

    model_string_keys = (
        "default_model_flash",
        "default_model_chat",
        "default_model_entity_chooser",
        "default_model_entity_combiner",
        "embedding_model",
        "intenserp_model_id",
    )
    for key in model_string_keys:
        normalized[key] = str(normalized.get(key, PRESET_SETTINGS_DEFAULTS[key]) or PRESET_SETTINGS_DEFAULTS[key]).strip()

    return normalized


def sanitize_settings(settings: dict) -> dict:
    """Normalize a flat settings dict without mutating persisted structure helpers."""
    data = dict(EFFECTIVE_SETTINGS_DEFAULTS)
    incoming = dict(settings or {})
    if "disable_safety_filters" in incoming and "gemini_disable_safety_filters" not in incoming:
        incoming["gemini_disable_safety_filters"] = incoming["disable_safety_filters"]
    if "chat_provider" in incoming and "default_model_chat_provider" not in incoming:
        _apply_chat_provider_alias(incoming, incoming.get("chat_provider"))

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

    data["disable_safety_filters"] = data["gemini_disable_safety_filters"]
    data["chat_provider"] = resolve_slot_provider(data, SLOT_CHAT)
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
    preset_values["default_model_flash"] = str(raw.get("default_model_flash", preset_values["default_model_flash"]) or preset_values["default_model_flash"]).strip()
    preset_values["default_model_chat"] = str(raw.get("default_model_chat", preset_values["default_model_chat"]) or preset_values["default_model_chat"]).strip()
    preset_values["default_model_entity_chooser"] = str(
        raw.get("default_model_entity_chooser", preset_values["default_model_entity_chooser"]) or preset_values["default_model_entity_chooser"]
    ).strip()
    preset_values["default_model_entity_combiner"] = str(
        raw.get("default_model_entity_combiner", preset_values["default_model_entity_combiner"]) or preset_values["default_model_entity_combiner"]
    ).strip()
    preset_values["embedding_model"] = str(raw.get("embedding_model", preset_values["embedding_model"]) or preset_values["embedding_model"]).strip()
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
    preset_values["gemini_disable_safety_filters"] = raw.get(
        "gemini_disable_safety_filters",
        raw.get("disable_safety_filters", preset_values["gemini_disable_safety_filters"]),
    )
    preset_values["gemini_chat_send_thinking"] = raw.get(
        "gemini_chat_send_thinking",
        preset_values["gemini_chat_send_thinking"],
    )
    preset_values["intenserp_model_id"] = str(raw.get("intenserp_model_id", preset_values["intenserp_model_id"]) or preset_values["intenserp_model_id"]).strip()

    thinking_keys = (
        "default_model_flash_thinking_level",
        "default_model_flash_thinking_manual",
        "default_model_chat_thinking_level",
        "default_model_chat_thinking_manual",
        "default_model_entity_chooser_thinking_level",
        "default_model_entity_chooser_thinking_manual",
        "default_model_entity_combiner_thinking_level",
        "default_model_entity_combiner_thinking_manual",
    )
    for key in thinking_keys:
        if key in raw:
            preset_values[key] = raw.get(key)

    legacy_chat_provider = raw.get("chat_provider", PROVIDER_GEMINI)
    _apply_chat_provider_alias(preset_values, legacy_chat_provider)

    preset = _build_default_preset(name=DEFAULT_PRESET_NAME)
    preset["values"] = _normalize_preset_values(preset_values)
    migrated["settings_presets"] = [preset]
    migrated["active_settings_preset_id"] = preset["id"]

    provider_credentials = {provider: [] for provider in PROVIDER_REGISTRY}
    provider_credentials[PROVIDER_GEMINI] = _build_legacy_provider_credentials_from_api_keys(raw.get("api_keys"))
    if raw.get("intenserp_base_url"):
        provider_credentials[PROVIDER_INTENSERP] = _normalize_provider_credential_entries(
            PROVIDER_INTENSERP,
            [
                {
                    "label": _default_provider_label(PROVIDER_INTENSERP, 1),
                    "enabled": True,
                    "base_url": raw.get("intenserp_base_url"),
                }
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
    if slot == SLOT_CHAT and "default_model_chat_provider" not in settings_data and "chat_provider" in settings_data:
        _apply_chat_provider_alias(settings_data, settings_data.get("chat_provider"))
    provider_field, openai_provider_field = _SLOT_PROVIDER_FIELDS[slot]
    family = _normalize_provider_family(slot, settings_data.get(provider_field))
    if family == "openai_compatible":
        return _normalize_openai_compatible_provider(settings_data.get(openai_provider_field))
    return family


def get_provider_env_fallback(provider: str) -> dict[str, Any] | None:
    info = PROVIDER_REGISTRY.get(provider)
    if not info:
        return None

    for env_var in info.get("env_api_key_vars", ()) or ():
        env_value = str(os.environ.get(env_var, "") or "").strip()
        if env_value and env_value != "your_key_here":
            return {
                "id": f"env:{provider}:{env_var}",
                "label": f"{info.get('display_name', provider)} env ({env_var})",
                "enabled": True,
                "api_key": env_value,
                "is_env_fallback": True,
            }
    for env_var in info.get("env_base_url_vars", ()) or ():
        env_value = str(os.environ.get(env_var, "") or "").strip()
        if env_value:
            return {
                "id": f"env:{provider}:{env_var}",
                "label": f"{info.get('display_name', provider)} env ({env_var})",
                "enabled": True,
                "base_url": env_value.rstrip("/"),
                "is_env_fallback": True,
            }
    if provider == PROVIDER_INTENSERP:
        return {
            "id": f"default:{provider}",
            "label": f"{info.get('display_name', provider)} default endpoint",
            "enabled": True,
            "base_url": str(info.get("default_base_url") or "").rstrip("/"),
            "is_env_fallback": True,
        }
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
    intense_pool = get_provider_pool(PROVIDER_INTENSERP)
    effective["intenserp_base_url"] = (
        str(intense_pool[0].get("base_url") or "")
        if intense_pool
        else str(PROVIDER_REGISTRY[PROVIDER_INTENSERP].get("default_base_url") or "")
    )
    return effective


def load_settings() -> dict:
    """Load the effective flat settings view used by the rest of the app."""
    raw_settings, changed = _load_raw_settings()
    if changed:
        _save_raw_settings(raw_settings)
    return _build_effective_settings(raw_settings)


def save_settings(settings: dict) -> None:
    """Persist flat configuration patches back into the active preset/top-level shape."""
    raw_settings, changed = _load_raw_settings()
    incoming = dict(settings or {})

    if "api_keys" in incoming:
        raw_settings["provider_credentials"][PROVIDER_GEMINI] = _build_legacy_provider_credentials_from_api_keys(
            incoming.get("api_keys"),
            existing_entries=raw_settings.get("provider_credentials", {}).get(PROVIDER_GEMINI, []),
        )
    if "provider_credentials" in incoming and isinstance(incoming["provider_credentials"], dict):
        raw_settings["provider_credentials"] = _normalize_provider_credentials_map(incoming["provider_credentials"])
    if "chat_provider" in incoming and "default_model_chat_provider" not in incoming:
        _apply_chat_provider_alias(incoming, incoming.get("chat_provider"))
    if "disable_safety_filters" in incoming and "gemini_disable_safety_filters" not in incoming:
        incoming["gemini_disable_safety_filters"] = incoming.get("disable_safety_filters")

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
    for key in CONFIGURATION_PRESET_KEYS:
        if key in incoming:
            preset_values[key] = incoming.get(key)
    active_preset["values"] = _normalize_preset_values(preset_values)

    _save_raw_settings(_normalize_raw_settings(raw_settings))


def create_settings_preset(name: str | None = None) -> dict[str, str]:
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
    raw_settings, changed = _load_raw_settings()
    for preset in raw_settings["settings_presets"]:
        if str(preset.get("id")) == preset_id:
            raw_settings["active_settings_preset_id"] = preset_id
            _save_raw_settings(_normalize_raw_settings(raw_settings))
            return {"id": preset_id, "name": str(preset.get("name") or "")}
    raise ValueError("Preset not found.")


def _serialize_text_model_options(provider: str) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for option in TEXT_MODEL_OPTIONS_BY_PROVIDER.get(provider, ()):
        gemini_levels = list(option.get("gemini_thinking_levels", ()))
        groq_reasoning_options = [dict(item) for item in option.get("groq_reasoning_options", ())]
        options.append(
            {
                "value": str(option["value"]),
                "label": str(option.get("label") or option["value"]),
                "supports_gemini_thinking": bool(gemini_levels),
                "gemini_thinking_levels": gemini_levels,
                "supports_groq_reasoning": bool(groq_reasoning_options),
                "groq_reasoning_options": groq_reasoning_options,
            }
        )
    return options


def _serialize_embedding_model_options(provider: str) -> list[dict[str, str]]:
    return [
        {
            "value": str(option["value"]),
            "label": str(option.get("label") or option["value"]),
            "provider": provider,
        }
        for option in EMBEDDING_MODEL_OPTIONS_BY_PROVIDER.get(provider, ())
    ]


def get_text_model_option(provider: str, model_name: object) -> dict[str, Any] | None:
    normalized = str(model_name or "").strip().lower()
    if not normalized:
        return None
    for option in TEXT_MODEL_OPTIONS_BY_PROVIDER.get(provider, ()):
        if str(option.get("value") or "").strip().lower() == normalized:
            return dict(option)
    return None


def get_embedding_model_option(provider: str, model_name: object) -> dict[str, Any] | None:
    normalized = str(model_name or "").strip().lower()
    if not normalized:
        return None
    for option in EMBEDDING_MODEL_OPTIONS_BY_PROVIDER.get(provider, ()):
        if str(option.get("value") or "").strip().lower() == normalized:
            return dict(option)
    return None


def get_provider_capabilities() -> dict[str, Any]:
    return {
        "providers": {
            provider: {
                "id": provider,
                "display_name": info["display_name"],
                "family": info["family"],
                "supported_slots": sorted(info["supported_slots"]),
                "required_credential_fields": list(info.get("required_credential_fields", ())),
                "credential_fields": list(info.get("credential_fields", ())),
                "supports_embedding": bool(info.get("supports_embedding")),
                "supports_gemini_safety": bool(info.get("supports_gemini_safety")),
                "supports_gemini_thinking": bool(info.get("supports_gemini_thinking")),
                "supports_groq_reasoning": bool(info.get("supports_groq_reasoning")),
                "text_model_options": _serialize_text_model_options(provider),
                "embedding_model_options": _serialize_embedding_model_options(provider),
            }
            for provider, info in PROVIDER_REGISTRY.items()
        },
        "families": {
            slot: dict(PROVIDER_FAMILY_OPTIONS[slot])
            for slot in PROVIDER_FAMILY_OPTIONS
        },
        "openai_compatible_providers": [
            {"value": provider, "label": PROVIDER_REGISTRY[provider]["display_name"]}
            for provider in OPENAI_COMPATIBLE_PROVIDERS
        ],
    }


def _build_missing_credential_message(provider: str, slot: str) -> str:
    provider_name = str(PROVIDER_REGISTRY.get(provider, {}).get("display_name") or provider)
    required = PROVIDER_REGISTRY.get(provider, {}).get("required_credential_fields", ())
    if required == ("api_key",):
        return f"{provider_name} is selected for {slot}, but no enabled API key is ready in Key Library."
    if required == ("base_url",):
        return f"{provider_name} is selected for {slot}, but no enabled base URL is ready in Key Library."
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
        elif slot == SLOT_EMBEDDING and not provider_info.get("supports_embedding", False):
            ok = False
            message = f"{provider_info.get('display_name', provider)} is not available for embeddings yet."
        elif not get_provider_pool(provider):
            ok = False
            message = _build_missing_credential_message(provider, slot_label)

        statuses[slot] = {
            "slot": slot,
            "provider": provider,
            "provider_family": provider_info.get("family"),
            "ok": ok,
            "severity": "ok" if ok else "error",
            "message": message,
            "supports_gemini_safety": bool(provider_info.get("supports_gemini_safety")),
            "supports_gemini_thinking": bool(provider_info.get("supports_gemini_thinking")),
            "supports_groq_reasoning": bool(provider_info.get("supports_groq_reasoning")),
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

    raw_settings, changed = _load_raw_settings()
    entries = list(raw_settings["provider_credentials"].get(provider, []))
    entry_id = str(payload.get("id") or uuid4().hex)
    updated_entry = {
        "id": entry_id,
        "label": str(payload.get("label") or "").strip() or _default_provider_label(provider, len(entries) + 1),
        "enabled": _coerce_bool(payload.get("enabled", True), True),
    }
    for field in PROVIDER_REGISTRY[provider].get("credential_fields", ()):
        field_name = field["name"]
        raw_value = payload.get(field_name)
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
    normalized = str(model_name or "").strip().lower()
    if not normalized:
        return []

    option = get_text_model_option(PROVIDER_GEMINI, model_name)
    if option:
        return [str(level) for level in option.get("gemini_thinking_levels", ())]

    for candidate in TEXT_MODEL_OPTIONS_BY_PROVIDER.get(PROVIDER_GEMINI, ()):
        value = str(candidate.get("value") or "").strip().lower()
        aliases = {value}
        if value.endswith("-preview"):
            aliases.add(value.removesuffix("-preview"))
        if any(normalized == alias or normalized.startswith(alias) for alias in aliases if alias):
            return [str(level) for level in candidate.get("gemini_thinking_levels", ())]
    return []


def get_supported_groq_reasoning_options(model_name: object) -> list[str]:
    option = get_text_model_option(PROVIDER_GROQ, model_name)
    if not option:
        return []
    output: list[str] = []
    for item in option.get("groq_reasoning_options", ()):
        value = str(item.get("value") or "").strip().lower()
        if value:
            output.append(value)
    return output


def resolve_groq_reasoning_effort(
    settings: dict,
    *,
    slot_key: str,
    model_name: object,
) -> str:
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
    return {
        "chunk_size_chars": int(settings_data.get("chunk_size_chars", TOP_LEVEL_SETTINGS_DEFAULTS["chunk_size_chars"])),
        "chunk_overlap_chars": int(settings_data.get("chunk_overlap_chars", TOP_LEVEL_SETTINGS_DEFAULTS["chunk_overlap_chars"])),
        "embedding_provider": str(settings_data.get("embedding_provider", PRESET_SETTINGS_DEFAULTS["embedding_provider"])),
        "embedding_openai_compatible_provider": str(
            settings_data.get(
                "embedding_openai_compatible_provider",
                PRESET_SETTINGS_DEFAULTS["embedding_openai_compatible_provider"],
            )
        ),
        "embedding_model": str(settings_data.get("embedding_model", PRESET_SETTINGS_DEFAULTS["embedding_model"])),
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
        else:
            output[key] = str(value)

    output["embedding_provider"] = _normalize_provider_family(SLOT_EMBEDDING, output.get("embedding_provider"))
    output["embedding_openai_compatible_provider"] = _normalize_openai_compatible_provider(
        output.get("embedding_openai_compatible_provider")
    )

    locked_at = stored.get("locked_at")
    if locked_at:
        output["locked_at"] = str(locked_at)
    last_ingest_settings_at = stored.get("last_ingest_settings_at")
    if last_ingest_settings_at:
        output["last_ingest_settings_at"] = str(last_ingest_settings_at)
    return output


def get_world_embedding_provider(world_id: str) -> str:
    ingest_settings = get_world_ingest_settings(world_id=world_id)
    return resolve_slot_provider(ingest_settings, SLOT_EMBEDDING)


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
        else:
            updated[key] = str(value)

    updated["embedding_provider"] = _normalize_provider_family(SLOT_EMBEDDING, updated.get("embedding_provider"))
    updated["embedding_openai_compatible_provider"] = _normalize_openai_compatible_provider(
        updated.get("embedding_openai_compatible_provider")
    )

    now = _now_iso()
    updated["locked_at"] = updated.get("locked_at") or (now if lock else None)
    if touch:
        updated["last_ingest_settings_at"] = now

    meta["ingest_settings"] = updated
    meta["embedding_model"] = updated["embedding_model"]
    meta["embedding_provider"] = resolve_slot_provider(updated, SLOT_EMBEDDING)
    meta["embedding_openai_compatible_provider"] = updated["embedding_openai_compatible_provider"]

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
