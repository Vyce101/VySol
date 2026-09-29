import pytest

from vysol.provider_profiles import preview_chat_models, profile_for


@pytest.mark.parametrize(("provider", "model", "expected_tested", "expected_api"), [
    ("google", "gemini-2.5-flash", True, "generate_content"),
    ("google", "gemini-3-pro-preview", True, "interactions"),
    ("google", "gemini-3.1-flash-lite", False, "interactions"),
    ("openai", "gpt-5.4", True, "responses"),
    ("anthropic", "claude-haiku-4-5-20251001", True, "messages"),
    ("deepseek", "deepseek-v4-pro", True, "chat_completions"),
    ("openai", "gpt-5.4-special-preview", False, "responses"),
])
def test_tested_profiles_are_exact_and_carry_api_contract(provider, model, expected_tested, expected_api):
    result = profile_for(provider, model)
    assert result["tested"] is expected_tested
    assert result["api"] == expected_api


def test_openai_catalog_separates_known_non_chat_models_from_unknown_chat_models():
    embedding = profile_for("openai", "text-embedding-future")
    image = profile_for("openai", "gpt-image-future")
    unknown_chat = profile_for("openai", "gpt-6-next")
    assert embedding["tested"] is False
    assert embedding["capabilities"]["chat"] is False
    assert embedding["capabilities"]["embeddings"] is True
    assert image["capabilities"]["chat"] is False
    assert image["capabilities"]["embeddings"] is False
    assert unknown_chat["tested"] is False
    assert unknown_chat["capabilities"]["chat"] is True
    assert unknown_chat["capabilities"]["embeddings"] is False


@pytest.mark.parametrize(("provider", "model_id"), [
    ("google", "gemini-2.5-flash-preview-tts"),
    ("google", "gemini-2.5-flash-image"),
    ("google", "gemini-3.1-pro-preview-customtools"),
    ("google", "gemini-3.5-flash-transcribe-preview"),
    ("google", "gemini-3.1-flash-tts-preview"),
    ("google", "lyria-3"),
    ("google", "gemini-robotics-er-2"),
    ("google", "antigravity-agent"),
    ("openai", "gpt-4o"),
    ("openai", "o3-deep-research"),
    ("openai", "computer-use-preview"),
])
def test_specialized_models_are_not_chat_models(provider, model_id):
    result = profile_for(provider, model_id, {"supportedGenerationMethods": ["generateContent"]})

    assert result["capabilities"]["chat"] is False


def test_non_chat_filter_preserves_embedding_discovery():
    embedding = profile_for("google", "gemini-embedding-2", {
        "supportedGenerationMethods": ["embedContent"],
    })

    assert embedding["capabilities"]["chat"] is False
    assert embedding["capabilities"]["embeddings"] is True


def test_preview_chat_models_contains_explicit_profiles_only():
    models = preview_chat_models()
    model_ids = {model["id"] for model in models}

    assert "gemini-3.8-flash" in model_ids
    assert "gpt-6-astra" in model_ids
    assert "claude-opus-5-5" in model_ids
    assert "deepseek-v4-pro" in model_ids
    assert "gemini-embedding-2" not in model_ids
    assert "gpt-4o" not in model_ids
    assert "gemini-3.1-pro-preview-customtools" not in model_ids
    assert "gemini-3.5-flash-transcribe-preview" not in model_ids
    assert "lyria-3" not in model_ids
    assert all(model["capabilities"]["chat"] is True for model in models)


def test_known_google_anthropic_and_deepseek_profiles_include_documented_limits():
    google_profile = profile_for("google", "gemini-2.5-pro")
    google = google_profile["capabilities"]
    assert google_profile["api"] == "generate_content"
    assert google["input_limit"] == 1_048_576
    assert google["output_limit"] == 65_536
    assert google["thinking_levels"] == []
    assert google["thinking_budget"] == {
        "minimum": 128, "maximum": 32_768, "default": "dynamic", "allow_zero": False,
    }

    flash = profile_for("google", "gemini-2.5-flash")
    assert flash["api"] == "generate_content"
    assert flash["capabilities"]["thinking_budget"] == {
        "minimum": 0, "maximum": 24_576, "default": "dynamic", "allow_zero": True,
    }

    flash_lite = profile_for("google", "gemini-2.5-flash-lite")
    assert flash_lite["api"] == "generate_content"
    assert flash_lite["capabilities"]["thinking_budget"] == {
        "minimum": 512, "maximum": 24_576, "default": "off", "allow_zero": True,
    }

    fable = profile_for("anthropic", "claude-fable-5-1")["capabilities"]
    assert fable["output_limit"] == 128_000
    assert fable["reasoning_default"] == "high"
    assert fable["thinking_mode"] == "adaptive"

    deepseek = profile_for("deepseek", "deepseek-v4-pro")
    assert deepseek["name"] == "DeepSeek V4 Pro"
    assert deepseek["series"] == "Pro"
    assert deepseek["capabilities"]["input_limit"] == 1_048_576
    assert deepseek["capabilities"]["output_limit"] == 393_216
    assert deepseek["capabilities"]["reasoning_levels"] == ["low", "high", "max"]
    assert deepseek["capabilities"]["reasoning_off"] is False

    deepseek_flash = profile_for("deepseek", "deepseek-flash")
    assert deepseek_flash["name"] == "DeepSeek V4.1 Flash"
    assert deepseek_flash["series"] == "Flash"

    gpt41 = profile_for("openai", "gpt-4.1")["capabilities"]
    assert gpt41["output_limit"] == 32_768
    assert gpt41["reasoning_levels"] == []


@pytest.mark.parametrize(("model", "input_limit", "output_limit"), [
    ("gpt-6-astra", 1_050_000, 128_000),
    ("gpt-5.4", 1_050_000, 128_000),
    ("gpt-5.4-pro", 1_050_000, 128_000),
    ("gpt-5-pro", 400_000, 272_000),
])
def test_openai_profile_uses_documented_decimal_limits(model, input_limit, output_limit):
    capabilities = profile_for("openai", model)["capabilities"]
    assert capabilities["input_limit"] == input_limit
    assert capabilities["output_limit"] == output_limit


def test_anthropic_manual_thinking_survives_provider_effort_metadata():
    result = profile_for("anthropic", "claude-haiku-4-5-20251001", {
        "max_input_tokens": 200000,
        "max_tokens": 64000,
        "capabilities": {"effort": {"supported": False},
                         "thinking": {"types": {"enabled": {"supported": True}}}},
    })
    capabilities = result["capabilities"]
    assert capabilities["thinking_mode"] == "manual"
    assert capabilities["reasoning_levels"] == ["low", "medium", "high"]
    assert capabilities["output_limit"] == 64000
