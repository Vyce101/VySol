"""Settings, presets, key library, and prompt endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.config import (
    LEGACY_REMOVED_KEYS,
    PROMPT_KEYS,
    PROVIDER_REGISTRY,
    activate_settings_preset,
    create_settings_preset,
    get_provider_library_payload,
    load_default_prompts,
    load_settings,
    remove_provider_credential,
    rename_settings_preset,
    save_settings,
    update_provider_credential_enabled,
    upsert_provider_credential,
)
from core.key_manager import get_key_manager

router = APIRouter()


class PromptUpdateRequest(BaseModel):
    key: str
    value: str


class PresetCreateRequest(BaseModel):
    name: str | None = None


class PresetRenameRequest(BaseModel):
    name: str


class CredentialUpsertRequest(BaseModel):
    id: str | None = None
    label: str | None = None
    enabled: bool = True
    api_key: str | None = None
    base_url: str | None = None


class CredentialEnabledRequest(BaseModel):
    enabled: bool


def _reload_provider_managers() -> None:
    for provider in PROVIDER_REGISTRY:
        try:
            get_key_manager(provider, force_reload=True)
        except Exception:
            continue


def _settings_payload() -> dict:
    settings = load_settings()
    for key in LEGACY_REMOVED_KEYS:
        settings.pop(key, None)
    settings["api_key_count"] = len(settings.get("api_keys", []))
    settings["api_key_active_count"] = sum(1 for entry in settings.get("api_keys", []) if bool(entry.get("enabled", True)))
    return settings


@router.get("")
async def get_settings():
    return _settings_payload()


@router.post("")
async def update_settings(body: dict):
    current = load_settings()
    for key in LEGACY_REMOVED_KEYS:
        current.pop(key, None)
    next_settings = dict(current)
    for key, value in body.items():
        if key in LEGACY_REMOVED_KEYS:
            continue
        next_settings[key] = value
    save_settings(next_settings)
    _reload_provider_managers()
    return _settings_payload()


@router.post("/presets")
async def create_preset(req: PresetCreateRequest):
    created = create_settings_preset(req.name)
    return {
        "preset": created,
        "settings": _settings_payload(),
    }


@router.post("/presets/{preset_id}/rename")
async def rename_preset(preset_id: str, req: PresetRenameRequest):
    try:
        renamed = rename_settings_preset(preset_id, req.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "preset": renamed,
        "settings": _settings_payload(),
    }


@router.post("/presets/{preset_id}/activate")
async def activate_preset(preset_id: str):
    try:
        activated = activate_settings_preset(preset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    _reload_provider_managers()
    return {
        "preset": activated,
        "settings": _settings_payload(),
    }


@router.get("/key-library")
async def get_key_library():
    return {
        "providers": {
            provider: get_provider_library_payload(provider)
            for provider in PROVIDER_REGISTRY
        }
    }


@router.get("/key-library/{provider}")
async def get_key_library_provider(provider: str):
    if provider not in PROVIDER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider.")
    return get_provider_library_payload(provider)


@router.post("/key-library/{provider}")
async def upsert_key_library_provider(provider: str, req: CredentialUpsertRequest):
    if provider not in PROVIDER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider.")
    try:
        payload = upsert_provider_credential(provider, req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _reload_provider_managers()
    return payload


@router.patch("/key-library/{provider}/{credential_id}")
async def patch_key_library_provider(provider: str, credential_id: str, req: CredentialEnabledRequest):
    if provider not in PROVIDER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider.")
    try:
        payload = update_provider_credential_enabled(provider, credential_id, req.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _reload_provider_managers()
    return payload


@router.delete("/key-library/{provider}/{credential_id}")
async def delete_key_library_provider(provider: str, credential_id: str):
    if provider not in PROVIDER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider.")
    try:
        payload = remove_provider_credential(provider, credential_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _reload_provider_managers()
    return payload


@router.get("/prompts")
async def get_prompts():
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
    if req.key not in PROMPT_KEYS:
        raise HTTPException(status_code=400, detail=f"Invalid prompt key. Must be one of: {PROMPT_KEYS}")
    settings = load_settings()
    settings[req.key] = req.value
    save_settings(settings)
    return {"ok": True}


@router.post("/prompts/reset/{key}")
async def reset_prompt(key: str):
    if key not in PROMPT_KEYS:
        raise HTTPException(status_code=400, detail=f"Invalid prompt key. Must be one of: {PROMPT_KEYS}")
    defaults = load_default_prompts()
    default_value = defaults.get(key, "")

    settings = load_settings()
    settings[key] = None
    save_settings(settings)

    return {"ok": True, "default_value": default_value}
