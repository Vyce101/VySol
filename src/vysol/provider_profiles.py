"""Model capability profiles used by provider discovery and chat settings."""

from __future__ import annotations

from copy import deepcopy


API_BY_PROVIDER = {
    "google": "interactions",
    "openai": "responses",
    "anthropic": "messages",
    "deepseek": "chat_completions",
    "openai_compatible": "chat_completions",
}

_EMPTY_CAPABILITIES = {
    "chat": None,
    "embeddings": None,
    "input_limit": None,
    "output_limit": None,
    "reasoning_levels": None,
    "reasoning_default": None,
    "reasoning_off": None,
    "thinking_levels": None,
    "thinking_default": None,
    "thinking_off": None,
    "thinking_mode": None,
    "thinking_budget": None,
    "embedding": None,
}

_NON_CHAT_MODEL_MARKERS = (
    "tts", "text-to-speech", "transcribe", "transcription", "audio", "omni",
    "image", "nano-banana", "lyria", "robotics", "computer-use", "computeruse",
    "antigravity", "deep-research", "deepresearch", "custom-tool", "custom-tools",
    "customtools",
)


def _google_profile(model_id: str) -> dict | None:
    model = model_id.lower()
    if model in {"gemini-3.8-flash", "gemini-3.7-flash"}:
        return {"series": "Flash", "capabilities": {
            "chat": True, "thinking_levels": ["low", "medium", "high"],
            "thinking_default": "medium", "thinking_off": False, "thinking_mode": "level",
            "input_limit": 1_048_576, "output_limit": 65_536,
        }}
    if model in {"gemini-3.6-flash", "gemini-3.5-flash"}:
        return {"series": "Flash", "capabilities": {
            "chat": True, "thinking_levels": ["minimal", "low", "medium", "high"],
            "thinking_default": "medium", "thinking_off": False, "thinking_mode": "level",
            "input_limit": 1_048_576, "output_limit": 65_536,
        }}
    if model == "gemini-3.1-pro-preview":
        return {"series": "Pro", "capabilities": {
            "chat": True, "thinking_levels": ["low", "medium", "high"],
            "thinking_default": "high", "thinking_off": False, "thinking_mode": "level",
            "input_limit": 1_048_576, "output_limit": 65_536,
        }}
    if model == "gemini-3.5-flash-lite":
        return {"series": "Flash Lite", "capabilities": {
            "chat": True, "thinking_levels": ["minimal", "low", "medium", "high"],
            "thinking_default": "minimal", "thinking_off": False, "thinking_mode": "level",
            "input_limit": 1_048_576, "output_limit": 65_536,
        }}
    if model == "gemini-3-pro-preview":
        return {"series": "Pro", "capabilities": {
            "chat": True, "thinking_levels": ["low", "high"],
            "thinking_default": "high", "thinking_off": False, "thinking_mode": "level",
            "input_limit": 1_048_576, "output_limit": 65_536,
        }}
    if model == "gemini-3-flash-preview":
        return {"series": "Flash", "capabilities": {
            "chat": True, "thinking_levels": ["minimal", "low", "medium", "high"],
            "thinking_default": "high", "thinking_off": False, "thinking_mode": "level",
            "input_limit": 1_048_576, "output_limit": 65_536,
        }}
    if model in {"gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"}:
        budget = {
            "gemini-2.5-pro": {
                "minimum": 128, "maximum": 32_768, "default": "dynamic", "allow_zero": False,
            },
            "gemini-2.5-flash": {
                "minimum": 0, "maximum": 24_576, "default": "dynamic", "allow_zero": True,
            },
            "gemini-2.5-flash-lite": {
                "minimum": 512, "maximum": 24_576, "default": "off", "allow_zero": True,
            },
        }[model]
        series = "Pro" if model.endswith("pro") else "Flash Lite" if model.endswith("flash-lite") else "Flash"
        return {
            "series": series,
            "api": "generate_content",
            "capabilities": {
                "chat": True,
                "thinking_levels": [],
                "thinking_default": budget["default"],
                "thinking_off": budget["allow_zero"],
                "thinking_mode": "budget",
                "thinking_budget": budget,
                "input_limit": 1_048_576, "output_limit": 65_536,
            },
        }
    if model in {"gemma-4-31b-it", "gemma-4-26b-a4b-it"}:
        return {"series": "Gemma", "capabilities": {"chat": True}}
    embedding_models = {
        "gemini-embedding-2", "gemini-embedding-2-preview", "gemini-embedding-001",
    }
    if model in embedding_models:
        dimensions = [768, 1536, 3072]
        maximum = 3072
        input_limit = 2048 if model == "gemini-embedding-001" else 8192
        return {"series": "Embeddings", "capabilities": {
            "chat": False, "embeddings": True,
            "embedding": {"dimensions": dimensions, "max_dimensions": maximum,
                          "input_limit": input_limit},
        }}
    return None


def _openai_profile(model_id: str) -> dict | None:
    model = model_id.lower()
    embedding_models = {
        "text-embedding-3-small": (1536, 8192),
        "text-embedding-3-large": (3072, 8192),
        "text-embedding-ada-002": (1536, 8192),
    }
    if model in embedding_models:
        dimensions, input_limit = embedding_models[model]
        return {"series": "Embeddings", "capabilities": {
            "chat": False, "embeddings": True,
            "embedding": {"dimensions": None, "max_dimensions": dimensions,
                          "input_limit": input_limit},
        }}
    gpt_profiles = {
        "gpt-6-astra": (1_050_000, 128_000, ["low", "medium", "high", "xhigh", "max"], "max", False),
        "gpt-6-sol": (1_050_000, 128_000, ["none", "low", "medium", "high", "xhigh", "max"], "medium", True),
        "gpt-6-luna": (1_050_000, 128_000, ["none", "low", "medium", "high", "xhigh", "max"], "medium", True),
        "gpt-5.6": (1_050_000, 128_000, ["none", "low", "medium", "high", "xhigh", "max"], "medium", True),
        "gpt-5.6-sol": (1_050_000, 128_000, ["none", "low", "medium", "high", "xhigh", "max"], "medium", True),
        "gpt-5.6-terra": (1_050_000, 128_000, ["none", "low", "medium", "high", "xhigh", "max"], "medium", True),
        "gpt-5.6-luna": (1_050_000, 128_000, ["none", "low", "medium", "high", "xhigh", "max"], "medium", True),
        "gpt-5.5": (1_050_000, 128_000, ["none", "low", "medium", "high", "xhigh"], "medium", True),
        "gpt-5.5-pro": (1_050_000, 128_000, ["medium", "high", "xhigh"], "high", False),
        "gpt-5.4": (1_050_000, 128_000, ["none", "low", "medium", "high", "xhigh"], "none", True),
        "gpt-5.4-mini": (400_000, 128_000, ["none", "low", "medium", "high", "xhigh"], "none", True),
        "gpt-5.4-nano": (400_000, 128_000, ["none", "low", "medium", "high", "xhigh"], "none", True),
        "gpt-5.4-pro": (1_050_000, 128_000, ["medium", "high", "xhigh"], "medium", False),
        "gpt-5.3-codex": (400_000, 128_000, ["low", "medium", "high", "xhigh"], "xhigh", False),
        "gpt-5.2": (400_000, 128_000, ["none", "low", "medium", "high", "xhigh"], "none", True),
        "gpt-5.2-pro": (400_000, 128_000, ["medium", "high", "xhigh"], "xhigh", False),
        "gpt-5.1": (400_000, 128_000, ["none", "low", "medium", "high"], "none", True),
        "gpt-5": (400_000, 128_000, ["minimal", "low", "medium", "high"], "medium", False),
        "gpt-5-mini": (400_000, 128_000, ["minimal", "low", "medium", "high"], "medium", False),
        "gpt-5-nano": (400_000, 128_000, ["minimal", "low", "medium", "high"], "medium", False),
        "gpt-5-pro": (400_000, 272_000, ["high"], "high", False),
        "gpt-4.1": (1_047_576, 32_768, [], None, False),
        "gpt-4.1-mini": (1_047_576, 32_768, [], None, False),
        "gpt-4o": (128_000, 16_384, [], None, False),
        "gpt-4o-mini": (128_000, 16_384, [], None, False),
        "o3": (200_000, 100_000, ["low", "medium", "high"], "high", False),
        "o3-pro": (200_000, 100_000, [], None, False),
    }
    if model in gpt_profiles:
        input_limit, output_limit, levels, default, can_disable = gpt_profiles[model]
        return {"series": "o Series" if model.startswith("o") else "GPT", "capabilities": {
            "chat": True, "input_limit": input_limit, "output_limit": output_limit,
            "reasoning_levels": levels, "reasoning_default": default,
            "reasoning_off": can_disable,
        }}
    return None


def _openai_catalog_capabilities(model_id: str) -> dict:
    model = model_id.lower()
    if model.startswith("text-embedding-"):
        return {"chat": False, "embeddings": True,
                "embedding": {"dimensions": None, "max_dimensions": None, "input_limit": None}}
    non_chat_prefixes = (
        "gpt-image-", "image-", "tts-", "whisper-", "audio-", "gpt-audio",
        "gpt-realtime", "omni-moderation", "text-moderation", "computer-use-",
    )
    if model.startswith(non_chat_prefixes):
        return {"chat": False, "embeddings": False}
    if model.startswith("gpt-"):
        return {"chat": True, "embeddings": False}
    return {}


_ANTHROPIC_ACTIVE = {
    "claude-fable-5", "claude-fable-5-1", "claude-opus-5", "claude-opus-5-5",
    "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6", "claude-opus-4-5-20251101",
    "claude-sonnet-5", "claude-sonnet-4-6", "claude-sonnet-4-5-20250929",
    "claude-haiku-4-5-20251001",
}


def _anthropic_profile(model_id: str) -> dict | None:
    model = model_id.lower()
    if model not in _ANTHROPIC_ACTIVE:
        return None
    family = ("Fable" if "fable" in model else "Opus" if "opus" in model else
              "Haiku" if "haiku" in model else "Sonnet")
    if model in {"claude-fable-5", "claude-fable-5-1"}:
        return {"series": "Fable", "capabilities": {
            "chat": True, "embeddings": False,
            "output_limit": 128_000,
            "reasoning_levels": ["low", "medium", "high", "xhigh", "max"],
            "reasoning_default": "high", "reasoning_off": False,
            "thinking_off": False, "thinking_mode": "adaptive",
        }}
    if model == "claude-opus-5-5":
        return {"series": "Opus", "capabilities": {
            "chat": True, "embeddings": False,
            "output_limit": 128_000,
            "reasoning_levels": ["low", "medium", "high", "xhigh", "max"],
            "reasoning_default": "medium", "reasoning_off": False,
            "thinking_off": False, "thinking_mode": "adaptive",
        }}
    if model == "claude-opus-5":
        return {"series": "Opus", "capabilities": {
            "chat": True, "embeddings": False,
            "output_limit": 128_000,
            "reasoning_levels": ["low", "medium", "high", "xhigh", "max"],
            "reasoning_default": "high", "reasoning_off": True,
            "thinking_off": True, "thinking_mode": "adaptive",
        }}
    if model in {"claude-sonnet-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6",
                 "claude-sonnet-4-6"}:
        family_levels = ["low", "medium", "high", "xhigh", "max"]
        if model in {"claude-opus-4-6", "claude-sonnet-4-6"}:
            family_levels = ["low", "medium", "high", "max"]
        return {"series": family, "capabilities": {
            "chat": True, "embeddings": False,
            "output_limit": 128_000,
            "reasoning_levels": family_levels,
            "reasoning_default": "high", "reasoning_off": True,
            "thinking_off": True, "thinking_mode": "adaptive",
        }}
    if model in {"claude-opus-4-5-20251101", "claude-sonnet-4-5-20250929",
                 "claude-haiku-4-5-20251001"}:
        return {"series": family, "capabilities": {
            "chat": True, "embeddings": False, "output_limit": 64_000,
            "reasoning_levels": ["low", "medium", "high"],
            "reasoning_default": "high", "reasoning_off": True,
            "thinking_off": True, "thinking_mode": "manual",
        }}
    return None


def _profile(provider: str, model_id: str) -> dict | None:
    if provider == "google":
        return _google_profile(model_id)
    if provider == "openai":
        return _openai_profile(model_id)
    if provider == "anthropic":
        return _anthropic_profile(model_id)
    if provider == "deepseek":
        model = model_id.lower()
        if model in {"deepseek-flash", "deepseek-v4-pro"}:
            return {"name": "DeepSeek V4.1 Flash" if model == "deepseek-flash" else "DeepSeek V4 Pro",
                    "series": "Flash" if model == "deepseek-flash" else "Pro",
                    "capabilities": {
                        "chat": True, "embeddings": False,
                        "input_limit": 1_048_576, "output_limit": 393_216,
                        "reasoning_levels": ["low", "high", "max"],
                        "reasoning_default": "high", "reasoning_off": False,
                    }}
    return None


def _number(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _is_non_chat_model(model_id: str, metadata: dict) -> bool:
    """Recognize dedicated media, agent, and tool models that cannot serve chat."""
    identifiers = [model_id]
    for field in ("displayName", "display_name", "name"):
        value = metadata.get(field)
        if isinstance(value, str):
            identifiers.append(value)

    for identifier in identifiers:
        normalized = identifier.casefold().replace("_", "-").replace(" ", "-")
        padded = f"-{normalized}-"
        if normalized.startswith("gpt-4o"):
            return True
        if any(f"-{marker}-" in padded for marker in _NON_CHAT_MODEL_MARKERS):
            return True
    return False


def _support(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, dict) and isinstance(value.get("supported"), bool):
        return value["supported"]
    return None


def _merge_google(capabilities: dict, metadata: dict) -> None:
    methods = metadata.get("supportedGenerationMethods")
    if isinstance(methods, list):
        capabilities["chat"] = "generateContent" in methods
        capabilities["embeddings"] = "embedContent" in methods
        if capabilities["embeddings"] and capabilities["embedding"] is None:
            capabilities["embedding"] = {"dimensions": None, "max_dimensions": None,
                                          "input_limit": _number(metadata.get("inputTokenLimit"))}
    input_limit = _number(metadata.get("inputTokenLimit"))
    output_limit = _number(metadata.get("outputTokenLimit"))
    if input_limit:
        capabilities["input_limit"] = input_limit
    if output_limit:
        capabilities["output_limit"] = output_limit
    if isinstance(metadata.get("thinking"), bool) and not metadata["thinking"]:
        capabilities.update(thinking_levels=[], thinking_default=None, thinking_off=False)


def _merge_anthropic(capabilities: dict, metadata: dict) -> None:
    capabilities["chat"] = True
    capabilities["embeddings"] = False
    capabilities["input_limit"] = _number(metadata.get("max_input_tokens")) or capabilities["input_limit"]
    capabilities["output_limit"] = _number(metadata.get("max_tokens")) or capabilities["output_limit"]
    provider_capabilities = metadata.get("capabilities")
    if not isinstance(provider_capabilities, dict):
        return
    effort = provider_capabilities.get("effort")
    if isinstance(effort, dict):
        levels = [level for level in ("low", "medium", "high", "xhigh", "max")
                  if _support(effort.get(level)) is True]
        if (_support(effort.get("supported")) is False
                and capabilities.get("thinking_mode") != "manual"):
            levels = []
        if levels:
            capabilities["reasoning_levels"] = levels
            default = effort.get("default") or effort.get("default_level")
            if default in levels:
                capabilities["reasoning_default"] = default
        elif (_support(effort.get("supported")) is False
              and capabilities.get("thinking_mode") != "manual"):
            capabilities["reasoning_levels"] = []
    thinking = provider_capabilities.get("thinking")
    if isinstance(thinking, dict):
        types = thinking.get("types") if isinstance(thinking.get("types"), dict) else {}
        adaptive = _support(types.get("adaptive"))
        manual = _support(types.get("enabled"))
        if adaptive is True:
            capabilities["thinking_mode"] = "adaptive"
        elif manual is True:
            capabilities["thinking_mode"] = "manual"
        elif _support(thinking.get("supported")) is False:
            capabilities["thinking_mode"] = None


def _merge_deepseek(capabilities: dict, metadata: dict) -> None:
    capabilities["chat"] = True
    capabilities["embeddings"] = False
    context = _number(metadata.get("context_window"))
    output = _number(metadata.get("max_output_tokens"))
    if context:
        capabilities["input_limit"] = context
    if output:
        capabilities["output_limit"] = output
    modalities = metadata.get("input_modalities")
    outputs = metadata.get("output_modalities")
    if isinstance(modalities, list) and isinstance(outputs, list):
        capabilities["chat"] = "text" in modalities and "text" in outputs
        capabilities["embeddings"] = False
    effort = metadata.get("effort")
    if isinstance(effort, dict):
        levels = effort.get("supported_levels")
        if isinstance(levels, list):
            capabilities["reasoning_levels"] = [level for level in levels
                                                 if isinstance(level, str) and level != "none"]
            default = effort.get("default_level")
            capabilities["reasoning_default"] = default if default in capabilities["reasoning_levels"] else None
            capabilities["reasoning_off"] = "none" in levels


def profile_for(provider: str, model_id: str, metadata: dict | None = None) -> dict:
    """Normalize one discovered model and merge known profile and provider metadata."""
    metadata = metadata if isinstance(metadata, dict) else {}
    profile = _profile(provider, model_id)
    capabilities = deepcopy(_EMPTY_CAPABILITIES)
    series = None
    if profile:
        series = profile.get("series")
        capabilities.update(deepcopy(profile.get("capabilities", {})))
    elif provider == "openai":
        inferred = _openai_catalog_capabilities(model_id)
        capabilities.update(inferred)
        if inferred.get("chat"):
            series = "GPT"
        elif inferred.get("embeddings"):
            series = "Embeddings"

    if provider == "google":
        _merge_google(capabilities, metadata)
    elif provider == "anthropic":
        _merge_anthropic(capabilities, metadata)
    elif provider == "deepseek":
        _merge_deepseek(capabilities, metadata)
    elif provider == "openai_compatible":
        capabilities["chat"] = None
        capabilities["embeddings"] = None

    if _is_non_chat_model(model_id, metadata):
        capabilities["chat"] = False

    name = metadata.get("displayName") or metadata.get("display_name") or metadata.get("name") or (profile or {}).get("name")
    if not isinstance(name, str) or not name.strip():
        name = model_id.replace("-", " ").replace("_", " ").title()
    metadata_known = any(value is not None for value in capabilities.values())
    source = "vysol" if profile else "provider" if metadata_known else "unknown"
    return {
        "id": model_id,
        "name": name.strip(),
        "provider": provider,
        "series": series,
        "tested": profile is not None,
        "capabilities": capabilities,
        "capability_source": source,
        "api": (profile or {}).get("api", API_BY_PROVIDER.get(provider)),
    }


_PREVIEW_CHAT_MODEL_IDS = {
    "google": (
        "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
        "gemini-3.1-pro-preview", "gemini-3.5-flash-lite", "gemini-3-pro-preview",
        "gemini-3-flash-preview", "gemini-2.5-pro", "gemini-2.5-flash",
        "gemini-2.5-flash-lite", "gemma-4-31b-it", "gemma-4-26b-a4b-it",
    ),
    "openai": (
        "gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-5.6-sol",
        "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5", "gpt-5.5-pro", "gpt-5.4",
        "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.4-pro", "gpt-5.3-codex", "gpt-5.2",
        "gpt-5.2-pro", "gpt-5.1", "gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5-pro",
        "gpt-4.1", "gpt-4.1-mini", "o3", "o3-pro",
    ),
    "anthropic": tuple(sorted(_ANTHROPIC_ACTIVE)),
    "deepseek": ("deepseek-flash", "deepseek-v4-pro"),
}


def preview_chat_models() -> list[dict]:
    """Return all explicitly profiled chat models for no-key interface previews."""
    return [
        model
        for provider, model_ids in _PREVIEW_CHAT_MODEL_IDS.items()
        for model_id in model_ids
        if (model := profile_for(provider, model_id))["capabilities"].get("chat") is True
    ]
