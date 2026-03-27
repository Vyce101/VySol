from core.ai_catalog import build_ai_catalog, validate_slot_config


def test_gemini_embeddings_exclude_gemini_1_5_flash():
    catalog = build_ai_catalog()
    embedding_models = {
        entry["value"]
        for entry in catalog["providers"]["gemini"]["models"]["embedding"]
    }
    assert "gemini/gemini-1.5-flash" not in embedding_models
    assert "gemini/gemini-embedding-001" in embedding_models


def test_custom_model_first_provider_accepts_unknown_model():
    normalized = validate_slot_config(
        "embedding",
        {
            "provider": "ollama",
            "model": "ollama/nomic-embed-text",
            "task": "embedding",
            "params": {},
        },
    )
    assert normalized["provider"] == "ollama"
    assert normalized["model"] == "ollama/nomic-embed-text"


def test_authoritative_provider_rejects_unknown_model():
    try:
        validate_slot_config(
            "chat",
            {
                "provider": "anthropic",
                "model": "anthropic/not-a-real-catalog-model",
                "task": "chat",
                "params": {},
            },
        )
    except ValueError as exc:
        assert "Unknown catalog model" in str(exc)
    else:
        raise AssertionError("Expected strict catalog validation to reject the unknown model.")


def test_chatgpt_provider_is_not_selectable():
    catalog = build_ai_catalog()
    assert catalog["providers"]["chatgpt"]["selectable"] is False


def test_selectable_providers_are_alphabetized_by_display_name():
    catalog = build_ai_catalog()
    provider_names = [
        entry["display_name"]
        for entry in catalog["providers"].values()
        if entry.get("selectable", True)
    ]
    assert provider_names == sorted(provider_names, key=lambda item: item.lower())
