from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .config import read_user_config, settings, user_config_path
from .ollama_support import DEFAULT_OLLAMA_BASE_URL, DEFAULT_OLLAMA_PULL_MODEL, get_ollama_runtime_status


@dataclass(frozen=True)
class ModelProfile:
    slug: str
    label: str
    summary: str
    reasoning: str
    coding: str
    fast: str


@dataclass(frozen=True)
class ProviderPreset:
    slug: str
    label: str
    description: str
    provider_value: str
    secret_env: str | None
    base_env: str | None = None
    base_default: str | None = None
    model_profiles: tuple[ModelProfile, ...] = ()
    notes: str = ""


MODEL_PROFILES = {
    "dashscope": (
        ModelProfile(
            slug="balanced",
            label="Qwen balanced",
            summary="Strong default for general coding and repo work.",
            reasoning="openai/qwen3.5-plus",
            coding="openai/qwen3-coder-next",
            fast="openai/qwen3.5-plus",
        ),
        ModelProfile(
            slug="coder-heavy",
            label="Qwen coder-heavy",
            summary="Bias toward coding throughput with the coder model on more steps.",
            reasoning="openai/qwen3-coder-next",
            coding="openai/qwen3-coder-next",
            fast="openai/qwen3.5-plus",
        ),
    ),
    "openai": (
        ModelProfile(
            slug="balanced",
            label="GPT-4o balanced",
            summary="General-purpose OpenAI default for reasoning and code.",
            reasoning="gpt-4o",
            coding="gpt-4o-mini",
            fast="gpt-4o-mini",
        ),
    ),
    "openrouter": (
        ModelProfile(
            slug="deepseek",
            label="OpenRouter DeepSeek mix",
            summary="Good default for coding-focused routing through OpenRouter.",
            reasoning="openrouter/openai/gpt-4o",
            coding="openrouter/deepseek/deepseek-chat",
            fast="openrouter/anthropic/claude-3-haiku",
        ),
    ),
    "anthropic": (
        ModelProfile(
            slug="sonnet",
            label="Claude Sonnet default",
            summary="Claude-heavy profile for teams preferring Anthropic.",
            reasoning="claude-3-5-sonnet-latest",
            coding="claude-3-5-sonnet-latest",
            fast="claude-3-5-haiku-latest",
        ),
    ),
    "azure-openai": (
        ModelProfile(
            slug="azure-default",
            label="Azure GPT default",
            summary="Azure OpenAI profile using GPT-4o and GPT-4o-mini defaults.",
            reasoning="azure/gpt-4o",
            coding="azure/gpt-4o",
            fast="azure/gpt-4o-mini",
        ),
    ),
    "openai-compatible": (
        ModelProfile(
            slug="compatible-default",
            label="Compatible endpoint default",
            summary="Generic OpenAI-compatible routing with a compact coder default.",
            reasoning="openai/gpt-4o-mini",
            coding="openai/gpt-4o-mini",
            fast="openai/gpt-4o-mini",
        ),
    ),
    "nvidia": (
        ModelProfile(
            slug="kimi-2-5",
            label="Kimi 2.5",
            summary="Moonshot AI Kimi 2.5 on NVIDIA's OpenAI-compatible runtime.",
            reasoning="openai/moonshotai/kimi-k2-5",
            coding="openai/moonshotai/kimi-k2-5",
            fast="openai/moonshotai/kimi-k2-5",
        ),
    ),
    "ollama": (
        ModelProfile(
            slug="local-default",
            label="Local Ollama default",
            summary="Local-only profile using the configured Ollama model.",
            reasoning=f"ollama/{DEFAULT_OLLAMA_PULL_MODEL}",
            coding=f"ollama/{DEFAULT_OLLAMA_PULL_MODEL}",
            fast=f"ollama/{DEFAULT_OLLAMA_PULL_MODEL}",
        ),
    ),
}


ALL_PROVIDER_CONFIG_KEYS: tuple[str, ...] = (
    "VIKI_PROVIDER",
    "VIKI_PROVIDER_ALLOW_FALLBACKS",
    "VIKI_REASONING_MODEL",
    "VIKI_CODING_MODEL",
    "VIKI_FAST_MODEL",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_API_BASE",
    "OPENAI_API_KEY",
    "OPENAI_API_BASE",
    "OPENAI_COMPAT_MODEL",
    "OPENROUTER_API_KEY",
    "OPENROUTER_API_BASE",
    "ANTHROPIC_API_KEY",
    "AZURE_API_KEY",
    "AZURE_API_BASE",
    "AZURE_API_VERSION",
    "GOOGLE_API_KEY",
    "DEEPSEEK_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "TOGETHERAI_API_KEY",
    "FIREWORKS_API_KEY",
    "XAI_API_KEY",
    "CEREBRAS_API_KEY",
    "SAMBANOVA_API_KEY",
    "NVIDIA_API_KEY",
    "NVIDIA_API_BASE",
    "NVIDIA_MODEL",
    "OLLAMA_BASE_URL",
    "OLLAMA_MODEL",
)

MESSAGING_CONFIG_KEYS: tuple[str, ...] = (
    "TELEGRAM_ENABLED",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_WEBHOOK_SECRET",
    "TELEGRAM_ALLOWED_CHAT_IDS",
    "WHATSAPP_ENABLED",
    "WHATSAPP_ACCOUNT_SID",
    "WHATSAPP_AUTH_TOKEN",
    "WHATSAPP_FROM_NUMBER",
    "WHATSAPP_ALLOWED_SENDERS",
    "WHATSAPP_WEBHOOK_URL",
)

MESSAGING_KEYS_BY_CHANNEL: dict[str, tuple[str, ...]] = {
    "telegram": (
        "TELEGRAM_ENABLED",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_WEBHOOK_SECRET",
        "TELEGRAM_ALLOWED_CHAT_IDS",
    ),
    "whatsapp": (
        "WHATSAPP_ENABLED",
        "WHATSAPP_ACCOUNT_SID",
        "WHATSAPP_AUTH_TOKEN",
        "WHATSAPP_FROM_NUMBER",
        "WHATSAPP_ALLOWED_SENDERS",
        "WHATSAPP_WEBHOOK_URL",
    ),
}


PROVIDER_PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        slug="dashscope",
        label="DashScope / Qwen",
        description="Alibaba Cloud Model Studio over the OpenAI-compatible API.",
        provider_value="dashscope",
        secret_env="DASHSCOPE_API_KEY",
        base_env="DASHSCOPE_API_BASE",
        base_default=settings.dashscope_api_base,
        model_profiles=MODEL_PROFILES["dashscope"],
    ),
    ProviderPreset(
        slug="openai",
        label="OpenAI",
        description="OpenAI direct API.",
        provider_value="openai",
        secret_env="OPENAI_API_KEY",
        model_profiles=MODEL_PROFILES["openai"],
    ),
    ProviderPreset(
        slug="openrouter",
        label="OpenRouter",
        description="OpenRouter aggregation with provider-side routing.",
        provider_value="openrouter",
        secret_env="OPENROUTER_API_KEY",
        base_env="OPENROUTER_API_BASE",
        base_default=settings.openrouter_api_base,
        model_profiles=MODEL_PROFILES["openrouter"],
    ),
    ProviderPreset(
        slug="anthropic",
        label="Anthropic",
        description="Anthropic Claude via LiteLLM.",
        provider_value="anthropic",
        secret_env="ANTHROPIC_API_KEY",
        model_profiles=MODEL_PROFILES["anthropic"],
    ),
    ProviderPreset(
        slug="azure-openai",
        label="Azure OpenAI",
        description="Azure-hosted OpenAI deployments.",
        provider_value="azure-openai",
        secret_env="AZURE_API_KEY",
        base_env="AZURE_API_BASE",
        model_profiles=MODEL_PROFILES["azure-openai"],
        notes="Azure also requires an API base URL and usually an API version.",
    ),
    ProviderPreset(
        slug="nvidia",
        label="NVIDIA",
        description="NVIDIA hosted models through the OpenAI-compatible transport.",
        provider_value="nvidia",
        secret_env="NVIDIA_API_KEY",
        base_env="NVIDIA_API_BASE",
        base_default="https://integrate.api.nvidia.com/v1",
        model_profiles=MODEL_PROFILES["nvidia"],
        notes="The NVIDIA preset uses the OpenAI-compatible transport under the hood, but VIKI keeps the setup and model selection product-friendly.",
    ),
    ProviderPreset(
        slug="openai-compatible",
        label="OpenAI-compatible",
        description="Any compatible endpoint with an API key and base URL.",
        provider_value="openai-compatible",
        secret_env="OPENAI_API_KEY",
        base_env="OPENAI_API_BASE",
        model_profiles=MODEL_PROFILES["openai-compatible"],
    ),
    ProviderPreset(
        slug="ollama",
        label="Ollama",
        description="Local Ollama endpoint for local models.",
        provider_value="ollama",
        secret_env=None,
        base_env="OLLAMA_BASE_URL",
        base_default=DEFAULT_OLLAMA_BASE_URL,
        model_profiles=MODEL_PROFILES["ollama"],
        notes="Ollama does not need an API key, but it does need a reachable local endpoint.",
    ),
)


def _dynamic_ollama_preset(base: ProviderPreset) -> ProviderPreset:
    status = get_ollama_runtime_status(allow_pull=False)
    model_name = status.selected_model or status.recommended_model
    profile = ModelProfile(
        slug="local-default",
        label=f"Local model: {model_name}",
        summary=(
            "Use the strongest detected local coding model."
            if status.selected_model
            else f"No suitable model is installed yet. VIKI will guide you toward {status.recommended_model}."
        ),
        reasoning=f"ollama/{model_name}",
        coding=f"ollama/{model_name}",
        fast=f"ollama/{model_name}",
    )
    notes = base.notes
    if status.error:
        notes = f"{base.notes} Current runtime status: {status.error}"
    elif status.selected_model:
        notes = f"{base.notes} Detected local coding model: {status.selected_model}."
    else:
        notes = f"{base.notes} Recommended local coding model: {status.recommended_model}."
    return ProviderPreset(
        slug=base.slug,
        label=base.label,
        description=base.description,
        provider_value=base.provider_value,
        secret_env=base.secret_env,
        base_env=base.base_env,
        base_default=status.base_url or base.base_default,
        model_profiles=(profile,),
        notes=notes,
    )


def _resolved_preset(preset: ProviderPreset) -> ProviderPreset:
    if preset.slug == "ollama":
        return _dynamic_ollama_preset(preset)
    return preset


def iter_provider_presets() -> Iterable[ProviderPreset]:
    for preset in PROVIDER_PRESETS:
        yield _resolved_preset(preset)


def get_provider_preset(slug: str) -> ProviderPreset:
    normalized = slug.strip().lower()
    for preset in iter_provider_presets():
        if preset.slug == normalized or preset.provider_value == normalized:
            return preset
    raise KeyError(slug)


def get_model_profile(preset: ProviderPreset, slug: str | None = None) -> ModelProfile:
    if not preset.model_profiles:
        raise KeyError(f"No model profiles are defined for {preset.slug}")
    if not slug:
        return preset.model_profiles[0]
    normalized = slug.strip().lower()
    for profile in preset.model_profiles:
        if profile.slug == normalized:
            return profile
    raise KeyError(slug)


def build_provider_env(preset: ProviderPreset, profile: ModelProfile, *, secret_value: str | None, base_value: str | None, azure_api_version: str | None = None) -> dict[str, str]:
    env = {
        "VIKI_PROVIDER": preset.provider_value,
        "VIKI_PROVIDER_ALLOW_FALLBACKS": "false",
        "VIKI_REASONING_MODEL": profile.reasoning,
        "VIKI_CODING_MODEL": profile.coding,
        "VIKI_FAST_MODEL": profile.fast,
    }
    if preset.secret_env and secret_value:
        env[preset.secret_env] = secret_value
    if preset.base_env and base_value:
        env[preset.base_env] = base_value
    if preset.slug == "azure-openai" and azure_api_version:
        env["AZURE_API_VERSION"] = azure_api_version
    if preset.slug == "openai-compatible" and not env.get("OPENAI_COMPAT_MODEL"):
        env["OPENAI_COMPAT_MODEL"] = profile.coding
    if preset.slug == "nvidia":
        if secret_value:
            env["NVIDIA_API_KEY"] = secret_value
        if base_value:
            env["NVIDIA_API_BASE"] = base_value
        env.setdefault("OPENAI_COMPAT_MODEL", profile.coding)
    if preset.slug == "ollama":
        env["OLLAMA_MODEL"] = profile.coding.removeprefix("ollama/")
    return env


def provider_reset_values() -> dict[str, None]:
    return {key: None for key in ALL_PROVIDER_CONFIG_KEYS}


def messaging_reset_values(*, enabled_channels: Iterable[str] = ()) -> dict[str, str | None]:
    enabled = {item.strip().lower() for item in enabled_channels}
    resets: dict[str, None | str] = {}
    for channel, keys in MESSAGING_KEYS_BY_CHANNEL.items():
        for index, key in enumerate(keys):
            if channel in enabled:
                if index == 0:
                    continue
                continue
            if index == 0:
                resets[key] = "false"
            else:
                resets[key] = None
    return resets


def onboarding_state(root: Path) -> dict[str, object]:
    config_values = read_user_config()
    workspace_root = root.resolve()
    workspace = workspace_root / settings.workspace_dir
    provider_value = settings.viki_provider or config_values.get("VIKI_PROVIDER") or ""
    config_exists = user_config_path().exists()
    provider_ready = bool(
        provider_value or any(
            config_values.get(key)
            for key in (
                "DASHSCOPE_API_KEY",
                "OPENAI_API_KEY",
                "OPENROUTER_API_KEY",
                "ANTHROPIC_API_KEY",
                "AZURE_API_KEY",
                "NVIDIA_API_KEY",
                "OLLAMA_BASE_URL",
            )
        )
    )
    return {
        "root": workspace_root,
        "workspace_ready": workspace.exists(),
        "workspace_path": workspace,
        "config_exists": config_exists,
        "provider_ready": provider_ready,
        "provider_value": provider_value or "unconfigured",
        "config_path": user_config_path(),
        "telegram_enabled": settings.telegram_enabled or config_values.get("TELEGRAM_ENABLED", "").lower() == "true",
        "whatsapp_enabled": settings.whatsapp_enabled or config_values.get("WHATSAPP_ENABLED", "").lower() == "true",
        "theme": settings.viki_theme,
        "approval_mode": settings.approval_mode,
        "run_mode": settings.default_run_mode,
    }
