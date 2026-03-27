"""LiteLLM-backed provider catalog and slot metadata."""

from __future__ import annotations

from functools import lru_cache
from importlib.metadata import version as package_version
import json
from typing import Any

import litellm

LITELLM_REQUIRED_VERSION = "1.82.6"

SLOT_FLASH = "flash"
SLOT_CHAT = "chat"
SLOT_ENTITY_CHOOSER = "entity_chooser"
SLOT_ENTITY_COMBINER = "entity_combiner"
SLOT_EMBEDDING = "embedding"

TASK_CHAT = "chat"
TASK_EMBEDDING = "embedding"

SLOT_TASKS: dict[str, str] = {
    SLOT_FLASH: TASK_CHAT,
    SLOT_CHAT: TASK_CHAT,
    SLOT_ENTITY_CHOOSER: TASK_CHAT,
    SLOT_ENTITY_COMBINER: TASK_CHAT,
    SLOT_EMBEDDING: TASK_EMBEDDING,
}

DEFAULT_SLOT_PARAMS: dict[str, dict[str, Any]] = {
    SLOT_FLASH: {"temperature": 0.1, "max_tokens": 8192, "reasoning_effort": "medium"},
    SLOT_CHAT: {"temperature": 1.0, "max_tokens": 8192, "reasoning_effort": "high"},
    SLOT_ENTITY_CHOOSER: {"temperature": 0.1, "max_tokens": 4096, "reasoning_effort": "medium"},
    SLOT_ENTITY_COMBINER: {"temperature": 0.2, "max_tokens": 4096, "reasoning_effort": "medium"},
    SLOT_EMBEDDING: {},
}

DEFAULT_SLOT_MODELS: dict[str, dict[str, str]] = {
    SLOT_FLASH: {
        "provider": "gemini",
        "model": "gemini/gemini-2.0-flash-lite",
        "task": TASK_CHAT,
    },
    SLOT_CHAT: {
        "provider": "gemini",
        "model": "gemini/gemini-2.0-flash",
        "task": TASK_CHAT,
    },
    SLOT_ENTITY_CHOOSER: {
        "provider": "gemini",
        "model": "gemini/gemini-2.0-flash-lite",
        "task": TASK_CHAT,
    },
    SLOT_ENTITY_COMBINER: {
        "provider": "gemini",
        "model": "gemini/gemini-2.0-flash-lite",
        "task": TASK_CHAT,
    },
    SLOT_EMBEDDING: {
        "provider": "gemini",
        "model": "gemini/gemini-embedding-001",
        "task": TASK_EMBEDDING,
    },
}

CUSTOM_MODEL_FIRST_PROVIDERS = {
    "huggingface",
    "nano-gpt",
    "nvidia_nim",
    "ollama",
    "openai_compatible",
    "openrouter",
}

NON_SELECTABLE_PROVIDERS = {
    "chatgpt",
}

PLACEHOLDER_MODELS: dict[str, dict[str, str]] = {
    "huggingface": {
        TASK_CHAT: "huggingface/meta-llama/Llama-3.1-8B-Instruct",
        TASK_EMBEDDING: "huggingface/sentence-transformers/all-MiniLM-L6-v2",
    },
    "nano-gpt": {
        TASK_CHAT: "nano-gpt/qwen/qwen3-32b",
    },
    "nvidia_nim": {
        TASK_CHAT: "nvidia_nim/meta/llama-3.1-70b-instruct",
    },
    "ollama": {
        TASK_CHAT: "ollama/llama3.1",
        TASK_EMBEDDING: "ollama/nomic-embed-text",
    },
    "openai_compatible": {
        TASK_CHAT: "openai/gpt-4.1-mini",
        TASK_EMBEDDING: "openai/text-embedding-3-small",
    },
    "openrouter": {
        TASK_CHAT: "openrouter/openai/gpt-4o-mini",
    },
}


def _field(name: str, label: str, *, secret: bool = False, multiline: bool = False, help_text: str | None = None) -> dict[str, Any]:
    payload = {
        "name": name,
        "label": label,
        "secret": secret,
        "multiline": multiline,
    }
    if help_text:
        payload["help_text"] = help_text
    return payload


PROVIDER_MANIFEST: dict[str, dict[str, Any]] = {
    "openai": {
        "display_name": "OpenAI",
        "supported_tasks": {TASK_CHAT, TASK_EMBEDDING},
        "supported_slots": {SLOT_FLASH, SLOT_CHAT, SLOT_ENTITY_CHOOSER, SLOT_ENTITY_COMBINER, SLOT_EMBEDDING},
        "required_credential_fields": ("api_key",),
        "credential_fields": (_field("api_key", "API Key", secret=True),),
        "env_field_vars": {"api_key": ("OPENAI_API_KEY",)},
        "catalog_source": "litellm",
        "model_prefix": "openai",
    },
    "anthropic": {
        "display_name": "Anthropic",
        "supported_tasks": {TASK_CHAT},
        "supported_slots": {SLOT_FLASH, SLOT_CHAT, SLOT_ENTITY_CHOOSER, SLOT_ENTITY_COMBINER},
        "required_credential_fields": ("api_key",),
        "credential_fields": (_field("api_key", "API Key", secret=True),),
        "env_field_vars": {"api_key": ("ANTHROPIC_API_KEY",)},
        "catalog_source": "litellm",
        "model_prefix": "anthropic",
    },
    "gemini": {
        "display_name": "Google AI Studio",
        "supported_tasks": {TASK_CHAT, TASK_EMBEDDING},
        "supported_slots": {SLOT_FLASH, SLOT_CHAT, SLOT_ENTITY_CHOOSER, SLOT_ENTITY_COMBINER, SLOT_EMBEDDING},
        "required_credential_fields": ("api_key",),
        "credential_fields": (_field("api_key", "API Key", secret=True),),
        "env_field_vars": {"api_key": ("GOOGLE_API_KEY", "GEMINI_API_KEY")},
        "catalog_source": "litellm",
        "model_prefix": "gemini",
        "provider_param_defs": (
            {
                "name": "thinking",
                "label": "Thinking JSON",
                "type": "json",
                "tasks": [TASK_CHAT],
                "help_text": "Provider-specific thinking payload passed through to LiteLLM.",
            },
            {
                "name": "safety_settings",
                "label": "Safety Settings JSON",
                "type": "json",
                "tasks": [TASK_CHAT],
                "help_text": "Optional Gemini safety settings payload.",
            },
        ),
    },
    "vertex_ai": {
        "display_name": "Vertex AI",
        "supported_tasks": {TASK_CHAT, TASK_EMBEDDING},
        "supported_slots": {SLOT_FLASH, SLOT_CHAT, SLOT_ENTITY_CHOOSER, SLOT_ENTITY_COMBINER, SLOT_EMBEDDING},
        "required_credential_fields": ("vertex_project", "vertex_location"),
        "credential_fields": (
            _field("vertex_project", "Project ID"),
            _field("vertex_location", "Location"),
            _field("vertex_credentials", "Service Account JSON", secret=True, multiline=True),
        ),
        "env_field_vars": {
            "vertex_project": ("VERTEXAI_PROJECT", "VERTEX_AI_PROJECT"),
            "vertex_location": ("VERTEXAI_LOCATION", "VERTEX_AI_LOCATION"),
            "vertex_credentials": ("VERTEXAI_CREDENTIALS",),
        },
        "catalog_source": "litellm",
        "model_prefix": "vertex_ai",
    },
    "zai": {
        "display_name": "Z.ai",
        "supported_tasks": {TASK_CHAT},
        "supported_slots": {SLOT_FLASH, SLOT_CHAT, SLOT_ENTITY_CHOOSER, SLOT_ENTITY_COMBINER},
        "required_credential_fields": ("api_key",),
        "credential_fields": (_field("api_key", "API Key", secret=True),),
        "catalog_source": "litellm",
        "model_prefix": "zai",
    },
    "xiaomi_mimo": {
        "display_name": "Xiaomi MiMo",
        "supported_tasks": {TASK_CHAT},
        "supported_slots": {SLOT_FLASH, SLOT_CHAT, SLOT_ENTITY_CHOOSER, SLOT_ENTITY_COMBINER},
        "required_credential_fields": ("api_key",),
        "credential_fields": (_field("api_key", "API Key", secret=True),),
        "catalog_source": "starter",
        "model_prefix": "xiaomi_mimo",
        "seed_models": (
            {"model": "xiaomi_mimo/mimo-v2-flash", "task": TASK_CHAT, "label": "MiMo V2 Flash"},
        ),
    },
    "xai": {
        "display_name": "xAI",
        "supported_tasks": {TASK_CHAT},
        "supported_slots": {SLOT_FLASH, SLOT_CHAT, SLOT_ENTITY_CHOOSER, SLOT_ENTITY_COMBINER},
        "required_credential_fields": ("api_key",),
        "credential_fields": (_field("api_key", "API Key", secret=True),),
        "env_field_vars": {"api_key": ("XAI_API_KEY",)},
        "catalog_source": "litellm",
        "model_prefix": "xai",
    },
    "openrouter": {
        "display_name": "OpenRouter",
        "supported_tasks": {TASK_CHAT},
        "supported_slots": {SLOT_FLASH, SLOT_CHAT, SLOT_ENTITY_CHOOSER, SLOT_ENTITY_COMBINER},
        "required_credential_fields": ("api_key",),
        "credential_fields": (_field("api_key", "API Key", secret=True),),
        "env_field_vars": {"api_key": ("OPENROUTER_API_KEY",)},
        "catalog_source": "litellm",
        "model_prefix": "openrouter",
    },
    "ollama": {
        "display_name": "Ollama",
        "supported_tasks": {TASK_CHAT, TASK_EMBEDDING},
        "supported_slots": {SLOT_FLASH, SLOT_CHAT, SLOT_ENTITY_CHOOSER, SLOT_ENTITY_COMBINER, SLOT_EMBEDDING},
        "required_credential_fields": (),
        "credential_fields": (
            _field("api_base", "Base URL", help_text="Defaults to http://localhost:11434"),
        ),
        "default_entry": {"api_base": "http://localhost:11434"},
        "env_field_vars": {"api_base": ("OLLAMA_API_BASE", "OLLAMA_BASE_URL")},
        "catalog_source": "litellm",
        "model_prefix": "ollama",
    },
    "nvidia_nim": {
        "display_name": "NVIDIA NIM",
        "supported_tasks": {TASK_CHAT},
        "supported_slots": {SLOT_FLASH, SLOT_CHAT, SLOT_ENTITY_CHOOSER, SLOT_ENTITY_COMBINER},
        "required_credential_fields": ("api_key",),
        "credential_fields": (
            _field("api_key", "API Key", secret=True),
            _field("api_base", "Base URL"),
        ),
        "env_field_vars": {"api_key": ("NVIDIA_NIM_API_KEY",)},
        "catalog_source": "mixed",
        "model_prefix": "nvidia_nim",
        "seed_models": (
            {"model": "nvidia_nim/meta/llama-3.1-8b-instruct", "task": TASK_CHAT, "label": "Llama 3.1 8B Instruct"},
            {"model": "nvidia_nim/meta/llama-3.1-70b-instruct", "task": TASK_CHAT, "label": "Llama 3.1 70B Instruct"},
        ),
    },
    "nano-gpt": {
        "display_name": "NanoGPT",
        "supported_tasks": {TASK_CHAT},
        "supported_slots": {SLOT_FLASH, SLOT_CHAT, SLOT_ENTITY_CHOOSER, SLOT_ENTITY_COMBINER},
        "required_credential_fields": ("api_key",),
        "credential_fields": (_field("api_key", "API Key", secret=True),),
        "env_field_vars": {"api_key": ("NANOGPT_API_KEY",)},
        "catalog_source": "starter",
        "model_prefix": "nano-gpt",
        "seed_models": (
            {"model": "nano-gpt/qwen/qwen3-32b", "task": TASK_CHAT, "label": "Qwen 3 32B"},
        ),
    },
    "moonshot": {
        "display_name": "Moonshot AI",
        "supported_tasks": {TASK_CHAT},
        "supported_slots": {SLOT_FLASH, SLOT_CHAT, SLOT_ENTITY_CHOOSER, SLOT_ENTITY_COMBINER},
        "required_credential_fields": ("api_key",),
        "credential_fields": (_field("api_key", "API Key", secret=True),),
        "env_field_vars": {"api_key": ("MOONSHOT_API_KEY",)},
        "catalog_source": "litellm",
        "model_prefix": "moonshot",
    },
    "minimax": {
        "display_name": "MiniMax",
        "supported_tasks": {TASK_CHAT},
        "supported_slots": {SLOT_FLASH, SLOT_CHAT, SLOT_ENTITY_CHOOSER, SLOT_ENTITY_COMBINER},
        "required_credential_fields": ("api_key",),
        "credential_fields": (_field("api_key", "API Key", secret=True),),
        "env_field_vars": {"api_key": ("MINIMAX_API_KEY",)},
        "catalog_source": "litellm",
        "model_prefix": "minimax",
    },
    "mistral": {
        "display_name": "Mistral AI API",
        "supported_tasks": {TASK_CHAT, TASK_EMBEDDING},
        "supported_slots": {SLOT_FLASH, SLOT_CHAT, SLOT_ENTITY_CHOOSER, SLOT_ENTITY_COMBINER, SLOT_EMBEDDING},
        "required_credential_fields": ("api_key",),
        "credential_fields": (_field("api_key", "API Key", secret=True),),
        "env_field_vars": {"api_key": ("MISTRAL_API_KEY",)},
        "catalog_source": "litellm",
        "model_prefix": "mistral",
    },
    "meta_llama": {
        "display_name": "Meta Llama",
        "supported_tasks": {TASK_CHAT},
        "supported_slots": {SLOT_FLASH, SLOT_CHAT, SLOT_ENTITY_CHOOSER, SLOT_ENTITY_COMBINER},
        "required_credential_fields": ("api_key",),
        "credential_fields": (_field("api_key", "API Key", secret=True),),
        "catalog_source": "litellm",
        "model_prefix": "meta_llama",
    },
    "huggingface": {
        "display_name": "Hugging Face",
        "supported_tasks": {TASK_CHAT, TASK_EMBEDDING},
        "supported_slots": {SLOT_FLASH, SLOT_CHAT, SLOT_ENTITY_CHOOSER, SLOT_ENTITY_COMBINER, SLOT_EMBEDDING},
        "required_credential_fields": ("api_key",),
        "credential_fields": (_field("api_key", "API Key", secret=True),),
        "env_field_vars": {"api_key": ("HF_TOKEN", "HUGGINGFACE_API_KEY")},
        "catalog_source": "starter",
        "model_prefix": "huggingface",
        "seed_models": (
            {"model": "huggingface/meta-llama/Llama-3.1-8B-Instruct", "task": TASK_CHAT, "label": "Meta Llama 3.1 8B Instruct"},
            {"model": "huggingface/sentence-transformers/all-MiniLM-L6-v2", "task": TASK_EMBEDDING, "label": "all-MiniLM-L6-v2"},
        ),
    },
    "groq": {
        "display_name": "Groq",
        "supported_tasks": {TASK_CHAT},
        "supported_slots": {SLOT_FLASH, SLOT_CHAT, SLOT_ENTITY_CHOOSER, SLOT_ENTITY_COMBINER},
        "required_credential_fields": ("api_key",),
        "credential_fields": (_field("api_key", "API Key", secret=True),),
        "env_field_vars": {"api_key": ("GROQ_API_KEY",)},
        "catalog_source": "litellm",
        "model_prefix": "groq",
    },
    "chatgpt": {
        "display_name": "ChatGPT Subscription",
        "supported_tasks": {TASK_CHAT},
        "supported_slots": {SLOT_FLASH, SLOT_CHAT, SLOT_ENTITY_CHOOSER, SLOT_ENTITY_COMBINER},
        "required_credential_fields": (),
        "credential_fields": (),
        "catalog_source": "litellm",
        "model_prefix": "chatgpt",
        "notes": "Uses LiteLLM ChatGPT device authentication. No API key is stored in the app.",
        "skip_model_introspection": True,
    },
    "deepseek": {
        "display_name": "DeepSeek",
        "supported_tasks": {TASK_CHAT},
        "supported_slots": {SLOT_FLASH, SLOT_CHAT, SLOT_ENTITY_CHOOSER, SLOT_ENTITY_COMBINER},
        "required_credential_fields": ("api_key",),
        "credential_fields": (_field("api_key", "API Key", secret=True),),
        "env_field_vars": {"api_key": ("DEEPSEEK_API_KEY",)},
        "catalog_source": "litellm",
        "model_prefix": "deepseek",
    },
    "cerebras": {
        "display_name": "Cerebras",
        "supported_tasks": {TASK_CHAT},
        "supported_slots": {SLOT_FLASH, SLOT_CHAT, SLOT_ENTITY_CHOOSER, SLOT_ENTITY_COMBINER},
        "required_credential_fields": ("api_key",),
        "credential_fields": (_field("api_key", "API Key", secret=True),),
        "env_field_vars": {"api_key": ("CEREBRAS_API_KEY",)},
        "catalog_source": "litellm",
        "model_prefix": "cerebras",
    },
    "openai_compatible": {
        "display_name": "OpenAI Compatible",
        "supported_tasks": {TASK_CHAT, TASK_EMBEDDING},
        "supported_slots": {SLOT_FLASH, SLOT_CHAT, SLOT_ENTITY_CHOOSER, SLOT_ENTITY_COMBINER, SLOT_EMBEDDING},
        "required_credential_fields": ("api_base",),
        "credential_fields": (
            _field("api_base", "Base URL"),
            _field("api_key", "API Key", secret=True),
            _field("api_version", "API Version"),
        ),
        "catalog_source": "starter",
        "model_prefix": "openai",
        "seed_models": (
            {"model": "openai/gpt-4.1-mini", "task": TASK_CHAT, "label": "GPT-4.1 Mini"},
            {"model": "openai/gpt-4o-mini", "task": TASK_CHAT, "label": "GPT-4o Mini"},
            {"model": "openai/text-embedding-3-small", "task": TASK_EMBEDDING, "label": "text-embedding-3-small"},
        ),
        "notes": "Catalog is a starter set because generic OpenAI-compatible servers do not expose one stable universal model list.",
    },
}

STANDARD_CHAT_PARAM_DEFS: dict[str, dict[str, Any]] = {
    "temperature": {"name": "temperature", "label": "Temperature", "type": "number", "min": 0, "max": 2, "step": 0.1},
    "top_p": {"name": "top_p", "label": "Top P", "type": "number", "min": 0, "max": 1, "step": 0.05},
    "max_tokens": {"name": "max_tokens", "label": "Max Tokens", "type": "integer", "min": 1, "step": 1},
    "max_completion_tokens": {"name": "max_completion_tokens", "label": "Max Completion Tokens", "type": "integer", "min": 1, "step": 1},
    "presence_penalty": {"name": "presence_penalty", "label": "Presence Penalty", "type": "number", "min": -2, "max": 2, "step": 0.1},
    "frequency_penalty": {"name": "frequency_penalty", "label": "Frequency Penalty", "type": "number", "min": -2, "max": 2, "step": 0.1},
    "seed": {"name": "seed", "label": "Seed", "type": "integer", "step": 1},
    "n": {"name": "n", "label": "Responses", "type": "integer", "min": 1, "step": 1},
    "reasoning_effort": {
        "name": "reasoning_effort",
        "label": "Reasoning Effort",
        "type": "enum",
        "options": [
            {"value": "low", "label": "Low"},
            {"value": "medium", "label": "Medium"},
            {"value": "high", "label": "High"},
            {"value": "xhigh", "label": "Extra High"},
            {"value": "none", "label": "None"},
        ],
    },
    "thinking": {"name": "thinking", "label": "Thinking JSON", "type": "json"},
}

STANDARD_EMBEDDING_PARAM_DEFS: dict[str, dict[str, Any]] = {
    "dimensions": {"name": "dimensions", "label": "Dimensions", "type": "integer", "min": 1, "step": 1},
    "encoding_format": {
        "name": "encoding_format",
        "label": "Encoding Format",
        "type": "enum",
        "options": [
            {"value": "float", "label": "Float"},
            {"value": "base64", "label": "Base64"},
        ],
    },
}


def ensure_litellm_version() -> str:
    """Return the installed LiteLLM version or raise if the pinned version is missing."""
    installed = package_version("litellm")
    if installed != LITELLM_REQUIRED_VERSION:
        raise RuntimeError(
            f"LiteLLM {LITELLM_REQUIRED_VERSION} is required, but {installed} is installed."
        )
    return installed


def get_default_slot_configs() -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for slot, defaults in DEFAULT_SLOT_MODELS.items():
        output[slot] = {
            "provider": defaults["provider"],
            "model": defaults["model"],
            "task": defaults["task"],
            "params": json.loads(json.dumps(DEFAULT_SLOT_PARAMS.get(slot, {}))),
        }
    return output


def get_provider_manifest() -> dict[str, dict[str, Any]]:
    return {
        provider: PROVIDER_MANIFEST[provider]
        for provider in sorted(
            PROVIDER_MANIFEST,
            key=lambda item: str(PROVIDER_MANIFEST[item].get("display_name") or item).lower(),
        )
    }


def get_provider_manifest_entry(provider: str) -> dict[str, Any] | None:
    return PROVIDER_MANIFEST.get(provider)


def provider_is_custom_model_first(provider: str) -> bool:
    return provider in CUSTOM_MODEL_FIRST_PROVIDERS


def provider_is_selectable(provider: str) -> bool:
    return provider not in NON_SELECTABLE_PROVIDERS


def get_provider_placeholder_model(provider: str, task: str) -> str:
    explicit = str(PLACEHOLDER_MODELS.get(provider, {}).get(task) or "").strip()
    if explicit:
        return _normalize_litellm_model(provider, explicit)
    manifest = PROVIDER_MANIFEST.get(provider, {})
    for seed in manifest.get("seed_models", ()) or ():
        if str(seed.get("task") or TASK_CHAT) == task:
            normalized = _normalize_litellm_model(provider, str(seed.get("model") or ""))
            if normalized:
                return normalized
    return ""


def _normalize_litellm_model(provider: str, model_name: str) -> str:
    raw_model = str(model_name or "").strip()
    if not raw_model:
        return raw_model
    if "/" in raw_model.split("/", 1)[0]:
        return raw_model
    prefix = str(PROVIDER_MANIFEST.get(provider, {}).get("model_prefix") or provider).strip()
    if raw_model.startswith(f"{prefix}/"):
        return raw_model
    if raw_model.startswith("openai/") and provider == "openai_compatible":
        return raw_model
    if raw_model.startswith(f"{provider}/"):
        return raw_model
    return f"{prefix}/{raw_model}" if prefix else raw_model


def _task_matches_slot(provider: str, task: str) -> bool:
    manifest = PROVIDER_MANIFEST.get(provider, {})
    return task in manifest.get("supported_tasks", set())


def _display_label_from_model(model_name: str) -> str:
    raw = str(model_name or "").strip()
    if not raw:
        return "-"
    tail = raw.split("/")[-1]
    return tail.replace("-", " ").replace("_", " ").strip() or raw


def _task_from_model_cost(provider: str, raw_key: str, payload: dict[str, Any]) -> str | None:
    mode = str(payload.get("mode") or "").strip().lower()
    task = TASK_EMBEDDING if mode == TASK_EMBEDDING else (TASK_CHAT if mode == TASK_CHAT else None)
    if task is None:
        return None
    normalized_model = _normalize_litellm_model(provider, raw_key)
    model_tail = normalized_model.split("/")[-1].lower()
    # LiteLLM 1.82.6 currently misclassifies some Gemini chat/text models as embeddings.
    if provider == "gemini":
        if task == TASK_EMBEDDING and "embedding" not in model_tail:
            return None
        if task == TASK_CHAT and "embedding" in model_tail:
            return None
    return task


def _read_model_cost_catalog(provider: str) -> dict[str, dict[str, dict[str, Any]]]:
    catalog = {TASK_CHAT: {}, TASK_EMBEDDING: {}}
    for raw_key, payload in litellm.model_cost.items():
        if not isinstance(payload, dict):
            continue
        raw_provider = str(payload.get("litellm_provider") or "").strip()
        if raw_provider != provider:
            continue
        task = _task_from_model_cost(provider, str(raw_key), payload)
        if task is None:
            continue
        normalized_model = _normalize_litellm_model(provider, str(raw_key))
        catalog[task][normalized_model] = {
            "value": normalized_model,
            "label": _display_label_from_model(normalized_model),
            "task": task,
            "mode": task,
            "catalog_source": "litellm",
            "max_input_tokens": payload.get("max_input_tokens"),
            "max_output_tokens": payload.get("max_output_tokens") or payload.get("max_tokens"),
            "output_vector_size": payload.get("output_vector_size"),
            "supports_function_calling": bool(payload.get("supports_function_calling")),
            "supports_response_schema": bool(payload.get("supports_response_schema")),
            "supports_vision": bool(payload.get("supports_vision")),
            "litellm_provider": raw_provider,
        }
    return catalog


def _merge_seed_models(provider: str, catalog: dict[str, dict[str, dict[str, Any]]]) -> None:
    manifest = PROVIDER_MANIFEST.get(provider, {})
    for seed in manifest.get("seed_models", ()) or ():
        task = str(seed.get("task") or TASK_CHAT)
        normalized_model = _normalize_litellm_model(provider, str(seed.get("model") or ""))
        if not normalized_model:
            continue
        catalog.setdefault(task, {})
        catalog[task].setdefault(
            normalized_model,
            {
                "value": normalized_model,
                "label": str(seed.get("label") or _display_label_from_model(normalized_model)),
                "task": task,
                "mode": task,
                "catalog_source": "manifest",
                "supports_function_calling": False,
                "supports_response_schema": False,
                "supports_vision": False,
                "litellm_provider": provider,
            },
        )


def _sort_catalog_items(items: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items.values(), key=lambda item: (str(item.get("label") or "").lower(), str(item.get("value") or "").lower()))


def _safe_get_supported_openai_params(provider: str, model_name: str) -> list[str]:
    manifest = PROVIDER_MANIFEST.get(provider, {})
    if manifest.get("skip_model_introspection"):
        if provider == "chatgpt":
            return ["temperature", "top_p", "max_tokens", "response_format", "stream", "tools", "tool_choice", "stop"]
        return []
    try:
        params = litellm.get_supported_openai_params(model=model_name)
    except Exception:
        return []
    return sorted({str(item) for item in params if str(item).strip()})


def _safe_get_model_info(provider: str, model_name: str) -> dict[str, Any]:
    manifest = PROVIDER_MANIFEST.get(provider, {})
    if manifest.get("skip_model_introspection"):
        return {}
    try:
        info = litellm.get_model_info(model_name)
    except Exception:
        return {}
    return dict(info or {})


def _enrich_model_entries(provider: str, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for entry in entries:
        model_name = str(entry.get("value") or "")
        info = _safe_get_model_info(provider, model_name)
        supported_params = _safe_get_supported_openai_params(provider, model_name)
        merged = dict(entry)
        if info:
            if info.get("mode") in {TASK_CHAT, TASK_EMBEDDING}:
                merged["mode"] = info["mode"]
            if info.get("max_input_tokens") is not None:
                merged["max_input_tokens"] = info.get("max_input_tokens")
            if info.get("max_output_tokens") is not None:
                merged["max_output_tokens"] = info.get("max_output_tokens")
            if info.get("output_vector_size") is not None:
                merged["output_vector_size"] = info.get("output_vector_size")
            merged["supports_function_calling"] = bool(info.get("supports_function_calling", merged.get("supports_function_calling")))
            merged["supports_response_schema"] = bool(info.get("supports_response_schema", merged.get("supports_response_schema")))
            merged["supports_vision"] = bool(info.get("supports_vision", merged.get("supports_vision")))
        merged["supported_params"] = supported_params
        enriched.append(merged)
    return enriched


def _build_provider_catalog(provider: str) -> dict[str, Any]:
    manifest = PROVIDER_MANIFEST[provider]
    raw_catalog = _read_model_cost_catalog(provider)
    _merge_seed_models(provider, raw_catalog)
    chat_models = _enrich_model_entries(provider, _sort_catalog_items(raw_catalog.get(TASK_CHAT, {})))
    embedding_models = _enrich_model_entries(provider, _sort_catalog_items(raw_catalog.get(TASK_EMBEDDING, {})))
    return {
        "id": provider,
        "display_name": manifest["display_name"],
        "supported_slots": sorted(manifest["supported_slots"]),
        "supported_tasks": sorted(manifest["supported_tasks"]),
        "required_credential_fields": list(manifest.get("required_credential_fields", ())),
        "credential_fields": list(manifest.get("credential_fields", ())),
        "catalog_source": str(manifest.get("catalog_source") or "litellm"),
        "custom_model_first": provider_is_custom_model_first(provider),
        "selectable": provider_is_selectable(provider),
        "placeholder_models": dict(PLACEHOLDER_MODELS.get(provider, {})),
        "notes": manifest.get("notes"),
        "models": {
            TASK_CHAT: chat_models,
            TASK_EMBEDDING: embedding_models,
        },
        "provider_param_defs": list(manifest.get("provider_param_defs", ())),
    }


@lru_cache(maxsize=1)
def build_ai_catalog() -> dict[str, Any]:
    ensure_litellm_version()
    providers = {
        provider: _build_provider_catalog(provider)
        for provider in sorted(
            PROVIDER_MANIFEST,
            key=lambda item: str(PROVIDER_MANIFEST[item].get("display_name") or item).lower(),
        )
    }
    return {
        "litellm_version": LITELLM_REQUIRED_VERSION,
        "slots": {
            slot: {"task": task}
            for slot, task in SLOT_TASKS.items()
        },
        "providers": providers,
        "common_params": {
            TASK_CHAT: list(STANDARD_CHAT_PARAM_DEFS.values()),
            TASK_EMBEDDING: list(STANDARD_EMBEDDING_PARAM_DEFS.values()),
        },
    }


def list_provider_ids() -> list[str]:
    return list(get_provider_manifest().keys())


def get_provider_entry(provider: str) -> dict[str, Any]:
    catalog = build_ai_catalog()
    if provider not in catalog["providers"]:
        raise ValueError("Unknown provider.")
    return dict(catalog["providers"][provider])


def get_models_for_provider(provider: str, task: str) -> list[dict[str, Any]]:
    entry = get_provider_entry(provider)
    return list(entry.get("models", {}).get(task, []))


def find_catalog_model(provider: str, task: str, model_name: str) -> dict[str, Any] | None:
    normalized_model = _normalize_litellm_model(provider, model_name)
    for entry in get_models_for_provider(provider, task):
        if str(entry.get("value") or "").strip().lower() == normalized_model.lower():
            return entry
    return None


def get_slot_param_defs(provider: str, task: str, model_name: str) -> dict[str, Any]:
    model_entry = find_catalog_model(provider, task, model_name)
    common_defs = STANDARD_CHAT_PARAM_DEFS if task == TASK_CHAT else STANDARD_EMBEDDING_PARAM_DEFS
    supported_params = set(model_entry.get("supported_params", []) if model_entry else [])
    if model_entry is None and provider_is_custom_model_first(provider):
        supported_params.update(common_defs.keys())
    typed = []
    untyped = []
    for param_name in sorted(supported_params):
        definition = common_defs.get(param_name)
        if definition:
            typed.append(dict(definition))
        else:
            untyped.append(param_name)
    provider_defs = []
    for definition in PROVIDER_MANIFEST.get(provider, {}).get("provider_param_defs", ()) or ():
        tasks = definition.get("tasks")
        if tasks and task not in tasks:
            continue
        provider_defs.append(dict(definition))
    return {
        "typed": typed,
        "provider_specific": provider_defs,
        "raw_supported_names": sorted(untyped),
    }


def _fallback_model_for_provider_task(provider: str, task: str, slot: str) -> str:
    placeholder = get_provider_placeholder_model(provider, task)
    if placeholder:
        return placeholder
    try:
        models = get_models_for_provider(provider, task)
    except Exception:
        models = []
    if models:
        return str(models[0].get("value") or "")
    default = get_default_slot_configs()[slot]
    if provider == default["provider"] and task == default["task"]:
        return str(default["model"] or "")
    return ""


def normalize_slot_config(slot: str, value: object) -> dict[str, Any]:
    default = get_default_slot_configs()[slot]
    incoming = value if isinstance(value, dict) else {}
    provider = str(incoming.get("provider") or default["provider"]).strip()
    if provider not in PROVIDER_MANIFEST or slot not in PROVIDER_MANIFEST[provider]["supported_slots"]:
        provider = default["provider"]
    task = SLOT_TASKS[slot]
    requested_model = str(incoming.get("model") or "").strip()
    model_name = _normalize_litellm_model(provider, requested_model)
    if not model_name:
        model_name = _fallback_model_for_provider_task(provider, task, slot)
    elif not find_catalog_model(provider, task, model_name) and not provider_is_custom_model_first(provider):
        model_name = _fallback_model_for_provider_task(provider, task, slot)
    params = incoming.get("params") if isinstance(incoming.get("params"), dict) else {}
    normalized_params = json.loads(json.dumps(params))
    return {
        "provider": provider,
        "model": model_name,
        "task": task,
        "params": normalized_params,
    }


def validate_slot_config(slot: str, value: object) -> dict[str, Any]:
    incoming = value if isinstance(value, dict) else {}
    default = get_default_slot_configs()[slot]
    requested_provider = str(incoming.get("provider") or default["provider"]).strip()
    provider = requested_provider
    if provider not in PROVIDER_MANIFEST or slot not in PROVIDER_MANIFEST[provider]["supported_slots"]:
        provider = default["provider"]
    task = SLOT_TASKS[slot]
    requested_model = _normalize_litellm_model(provider, str(incoming.get("model") or "").strip())
    if requested_model and not provider_is_custom_model_first(provider) and not find_catalog_model(provider, task, requested_model):
        raise ValueError(f"Unknown catalog model '{requested_model}' for provider '{provider}'.")

    normalized = normalize_slot_config(slot, value)
    provider = normalized["provider"]
    task = normalized["task"]
    model_name = normalized["model"]
    provider_entry = get_provider_entry(provider)
    if task not in provider_entry.get("supported_tasks", []):
        raise ValueError(f"{provider_entry.get('display_name', provider)} does not support {task}.")
    model_entry = find_catalog_model(provider, task, model_name)
    if model_entry is None and not provider_is_custom_model_first(provider):
        raise ValueError(f"Unknown catalog model '{model_name}' for provider '{provider}'.")
    if model_entry is not None and task != model_entry.get("task"):
        raise ValueError(f"Model '{model_name}' is not available for {task}.")
    if not str(model_name or "").strip():
        raise ValueError(f"A model id is required for provider '{provider}'.")
    common_defs = STANDARD_CHAT_PARAM_DEFS if task == TASK_CHAT else STANDARD_EMBEDDING_PARAM_DEFS
    supported_names = set(model_entry.get("supported_params", []) if model_entry else [])
    if model_entry is None and provider_is_custom_model_first(provider):
        supported_names.update(common_defs.keys())
    provider_specific_names = {
        str(item.get("name") or "")
        for item in provider_entry.get("provider_param_defs", [])
        if not item.get("tasks") or task in item.get("tasks", [])
    }
    allowed = supported_names.union(provider_specific_names)
    for key in list(normalized["params"].keys()):
        if key not in allowed:
            raise ValueError(f"Parameter '{key}' is not supported by {model_name}.")
    return normalized


def provider_supports_embeddings(provider: str) -> bool:
    return TASK_EMBEDDING in PROVIDER_MANIFEST.get(provider, {}).get("supported_tasks", set())
