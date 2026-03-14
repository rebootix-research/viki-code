from __future__ import annotations

import os
from unittest.mock import patch

from typer.testing import CliRunner

from viki.cli import app
from viki.onboarding import get_model_profile, get_provider_preset
from viki.providers.litellm_provider import LiteLLMProvider


runner = CliRunner()


def test_litellm_provider_prefers_requested_backend_and_dynamic_models():
    with patch.dict(
        os.environ,
        {
            "OPENROUTER_API_KEY": "redacted",
            "DASHSCOPE_API_KEY": "redacted",
            "DASHSCOPE_API_BASE": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            "VIKI_PROVIDER": "openrouter",
            "VIKI_CODING_MODEL": "openrouter/anthropic/claude-3-haiku",
        },
        clear=False,
    ):
        provider = LiteLLMProvider()
        if not provider._available:
            return
        diagnostics = provider.diagnostics()
        assert diagnostics["selected_provider"] == "openrouter"
        assert diagnostics["fallback_chain"][0] == "openrouter"
        assert "dashscope" in diagnostics["configured_backends"]
        assert diagnostics["model_slots"]["coding"] == "openrouter/anthropic/claude-3-haiku"


def test_litellm_provider_surfaces_openai_compatible_backend():
    with patch.dict(
        os.environ,
        {
            "OPENAI_API_KEY": "redacted",
            "OPENAI_API_BASE": "https://compatible.example.com/v1",
            "OPENAI_COMPAT_MODEL": "openai/custom-coder",
        },
        clear=True,
    ):
        provider = LiteLLMProvider()
        if not provider._available:
            return
        diagnostics = provider.diagnostics()
        assert "openai-compatible" in provider.available_backends()
        assert diagnostics["selected_provider"] == "openai-compatible"
        assert diagnostics["model_slots"]["coding"] == "openai/custom-coder"


def test_cli_plain_providers_command_reports_selection():
    result = runner.invoke(
        app,
        ["--plain", "providers"],
        env={
            "DASHSCOPE_API_KEY": "redacted",
            "DASHSCOPE_API_BASE": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            "VIKI_PROVIDER": "dashscope",
            "VIKI_CODING_MODEL": "openai/qwen3-coder-next",
        },
    )
    assert result.exit_code == 0, result.output
    assert "Selected provider" in result.output
    assert "dashscope" in result.output
    assert "Coding model" in result.output
    assert "openai/qwen3-coder-next" in result.output


def test_nvidia_onboarding_preset_maps_to_openai_compatible_transport():
    preset = get_provider_preset("nvidia")
    profile = get_model_profile(preset, "kimi-2-5")

    assert preset.provider_value == "nvidia"
    assert preset.base_default == "https://integrate.api.nvidia.com/v1"
    assert profile.coding == "openai/moonshotai/kimi-k2-5"


def test_litellm_provider_surfaces_nvidia_backend_cleanly():
    with patch.dict(
        os.environ,
        {
            "NVIDIA_API_KEY": "redacted",
            "NVIDIA_API_BASE": "https://integrate.api.nvidia.com/v1",
            "VIKI_PROVIDER": "nvidia",
        },
        clear=True,
    ):
        provider = LiteLLMProvider()
        if not provider._available:
            return
        diagnostics = provider.diagnostics()
        assert diagnostics["selected_provider"] == "nvidia"
        assert diagnostics["model_slots"]["coding"] == "openai/moonshotai/kimi-k2-5"
