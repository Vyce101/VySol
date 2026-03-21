"""Settings & Prompts endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.config import load_settings, save_settings, load_default_prompts
from core.key_manager import get_key_manager

router = APIRouter()

REMOVED_SETTINGS_KEYS = {
    "use_single_agent",
    "enable_claims",
    "default_model_scribe",
    "entity_architect_prompt",
    "relationship_architect_prompt",
    "claim_architect_prompt",
    "scribe_prompt",
    "ingestion_concurrency",
}


class PromptUpdateRequest(BaseModel):
    key: str
    value: str


# ── Settings ───────────────────────────────────────────────────────────

@router.get("")
async def get_settings():
    """GET settings."""
    settings = load_settings()
    for key in REMOVED_SETTINGS_KEYS:
        settings.pop(key, None)
    api_keys = settings.get("api_keys", [])
    return {
        **settings,
        "api_key_count": len(api_keys),
        "api_key_active_count": sum(1 for entry in api_keys if bool(entry.get("enabled", True))),
    }


@router.post("")
async def update_settings(body: dict):
    """POST partial settings update."""
    current = load_settings()
    for key in REMOVED_SETTINGS_KEYS:
        current.pop(key, None)
    for key, value in body.items():
        if key in REMOVED_SETTINGS_KEYS:
            continue
        current[key] = value
    save_settings(current)

    # Reinitialise KeyManager if keys changed
    if "api_keys" in body or "key_rotation_mode" in body:
        get_key_manager(force_reload=True)

    return {
        **{k: v for k, v in current.items() if k != "api_keys"},
        "api_key_count": len(current.get("api_keys", [])),
        "api_key_active_count": sum(1 for entry in current.get("api_keys", []) if bool(entry.get("enabled", True))),
    }


# ── Prompts ────────────────────────────────────────────────────────────

PROMPT_KEYS = [
    "graph_architect_prompt",
    "entity_resolution_chooser_prompt",
    "entity_resolution_combiner_prompt",
    "chat_system_prompt",
]


@router.get("/prompts")
async def get_prompts():
    """Get all prompts with their source (custom vs default)."""
    settings = load_settings()
    defaults = load_default_prompts()
    result = {}
    for key in PROMPT_KEYS:
        custom_val = settings.get(key)
        if custom_val:
            result[key] = {"value": custom_val, "source": "custom"}
        else:
            result[key] = {"value": defaults.get(key, ""), "source": "default"}
    return result


@router.post("/prompts")
async def update_prompt(req: PromptUpdateRequest):
    """Save a custom prompt."""
    if req.key not in PROMPT_KEYS:
        raise HTTPException(status_code=400, detail=f"Invalid prompt key. Must be one of: {PROMPT_KEYS}")
    settings = load_settings()
    settings[req.key] = req.value
    save_settings(settings)
    return {"ok": True}


@router.post("/prompts/reset/{key}")
async def reset_prompt(key: str):
    """Reset a prompt to its default value."""
    if key not in PROMPT_KEYS:
        raise HTTPException(status_code=400, detail=f"Invalid prompt key. Must be one of: {PROMPT_KEYS}")
    defaults = load_default_prompts()
    default_value = defaults.get(key, "")

    settings = load_settings()
    settings[key] = None  # null = fall back to default
    save_settings(settings)

    return {"ok": True, "default_value": default_value}
