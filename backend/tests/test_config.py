from core.config import TOP_LEVEL_SETTINGS_DEFAULTS, sanitize_settings


def test_sanitize_settings_normalizes_node_description_limit_default_and_clamps() -> None:
    defaults = sanitize_settings({})
    assert defaults["retrieval_max_node_description_chars"] == TOP_LEVEL_SETTINGS_DEFAULTS["retrieval_max_node_description_chars"] == 0

    clamped = sanitize_settings({"retrieval_max_node_description_chars": -25})
    assert clamped["retrieval_max_node_description_chars"] == 0

    explicit = sanitize_settings({"retrieval_max_node_description_chars": "42"})
    assert explicit["retrieval_max_node_description_chars"] == 42
