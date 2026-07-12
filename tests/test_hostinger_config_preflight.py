from __future__ import annotations

from scripts.validate_hostinger_environment import validate_environment


def _safe_environment() -> dict[str, str]:
    return {
        "SECRET_KEY": "s" * 48,
        "LLM_API_KEY": "l" * 32,
        "LLM_BASE_URL": "https://llm-provider.test/v1",
        "LLM_MODEL_NAME": "model-enabled-for-account",
        "ZEP_API_KEY": "z" * 32,
        "TRADING_MODE": "paper",
        "EXECUTION_MODE": "paper",
        "ENABLE_LIVE_TRADING": "false",
        "LIVE_TRADING_ARMED": "false",
        "LIVE_EXECUTION_MODE": "paper",
        "ENABLE_MIROFISH": "true",
        "MIROFISH_PROVIDER": "external",
    }


def test_hostinger_preflight_accepts_safe_configuration_shape() -> None:
    assert validate_environment(_safe_environment()) == []


def test_hostinger_preflight_rejects_placeholders_without_leaking_values() -> None:
    values = _safe_environment()
    values.update(
        {
            "SECRET_KEY": "replace_with_a_long_random_value",
            "LLM_API_KEY": "replace_with_rotated_llm_key",
            "LLM_BASE_URL": "https://your-openai-compatible-provider.example/v1",
            "LLM_MODEL_NAME": "replace_with_model_name",
            "ZEP_API_KEY": "replace_with_rotated_zep_key",
        }
    )

    errors = validate_environment(values)

    assert "SECRET_KEY:placeholder" in errors
    assert "LLM_API_KEY:placeholder" in errors
    assert "LLM_BASE_URL:placeholder" in errors
    assert "LLM_MODEL_NAME:placeholder" in errors
    assert "ZEP_API_KEY:placeholder" in errors
    assert not any(values["LLM_API_KEY"] in error for error in errors)


def test_hostinger_preflight_rejects_any_live_enablement() -> None:
    values = _safe_environment()
    values["ENABLE_LIVE_TRADING"] = "true"
    values["LIVE_TRADING_ARMED"] = "true"
    values["LIVE_EXECUTION_MODE"] = "live"

    errors = validate_environment(values)

    assert "ENABLE_LIVE_TRADING:expected_false" in errors
    assert "LIVE_TRADING_ARMED:expected_false" in errors
    assert "LIVE_EXECUTION_MODE:expected_paper" in errors
