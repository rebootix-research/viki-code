from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .._log import structlog
from ..config import settings
from ..ollama_support import DEFAULT_OLLAMA_BASE_URL, get_ollama_runtime_status
from .base import LLMProvider

logger = structlog.get_logger()

ROLE_NAMES = ("reasoning", "coding", "fast")


@dataclass(frozen=True)
class Backend:
    name: str
    description: str
    required_envs: tuple[str, ...]
    defaults: tuple[str, str, str]
    base_env: Optional[str] = None
    base_default: Optional[str] = None
    prefixes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedCandidate:
    backend: str
    model: str
    kwargs: Dict[str, Any]


BACKENDS: dict[str, Backend] = {
    "dashscope": Backend(
        name="dashscope",
        description="Alibaba Cloud Model Studio / DashScope via OpenAI-compatible transport",
        required_envs=("DASHSCOPE_API_KEY",),
        defaults=(
            "openai/qwen3.5-plus",
            "openai/qwen3-coder-next",
            "openai/qwen3.5-plus",
        ),
        base_env="DASHSCOPE_API_BASE",
        base_default=settings.dashscope_api_base,
        prefixes=("openai/qwen", "qwen"),
    ),
    "openrouter": Backend(
        name="openrouter",
        description="OpenRouter aggregation layer",
        required_envs=("OPENROUTER_API_KEY",),
        defaults=(
            "openrouter/openai/gpt-4o",
            "openrouter/deepseek/deepseek-chat",
            "openrouter/anthropic/claude-3-haiku",
        ),
        base_env="OPENROUTER_API_BASE",
        base_default="https://openrouter.ai/api/v1",
        prefixes=("openrouter/",),
    ),
    "openai": Backend(
        name="openai",
        description="OpenAI direct API",
        required_envs=("OPENAI_API_KEY",),
        defaults=("gpt-4o", "gpt-4o-mini", "gpt-4o-mini"),
        base_env="OPENAI_API_BASE",
        prefixes=("gpt-", "o1", "o3", "o4", "openai/"),
    ),
    "nvidia": Backend(
        name="nvidia",
        description="NVIDIA hosted models through the OpenAI-compatible transport",
        required_envs=("NVIDIA_API_KEY", "NVIDIA_API_BASE"),
        defaults=(
            "openai/moonshotai/kimi-k2-5",
            "openai/moonshotai/kimi-k2-5",
            "openai/moonshotai/kimi-k2-5",
        ),
        base_env="NVIDIA_API_BASE",
        base_default="https://integrate.api.nvidia.com/v1",
        prefixes=("openai/moonshotai/", "moonshotai/"),
    ),
    "anthropic": Backend(
        name="anthropic",
        description="Anthropic Claude via LiteLLM",
        required_envs=("ANTHROPIC_API_KEY",),
        defaults=(
            "claude-3-5-sonnet-latest",
            "claude-3-5-sonnet-latest",
            "claude-3-5-haiku-latest",
        ),
        prefixes=("claude",),
    ),
    "google": Backend(
        name="google",
        description="Google Gemini via LiteLLM",
        required_envs=("GOOGLE_API_KEY",),
        defaults=(
            "gemini/gemini-1.5-pro",
            "gemini/gemini-1.5-pro",
            "gemini/gemini-2.0-flash",
        ),
        prefixes=("gemini/",),
    ),
    "deepseek": Backend(
        name="deepseek",
        description="DeepSeek direct API",
        required_envs=("DEEPSEEK_API_KEY",),
        defaults=(
            "deepseek/deepseek-reasoner",
            "deepseek/deepseek-chat",
            "deepseek/deepseek-chat",
        ),
        prefixes=("deepseek/",),
    ),
    "groq": Backend(
        name="groq",
        description="Groq low-latency inference",
        required_envs=("GROQ_API_KEY",),
        defaults=(
            "groq/llama-3.3-70b-versatile",
            "groq/llama-3.3-70b-versatile",
            "groq/llama-3.1-8b-instant",
        ),
        prefixes=("groq/",),
    ),
    "mistral": Backend(
        name="mistral",
        description="Mistral direct API",
        required_envs=("MISTRAL_API_KEY",),
        defaults=(
            "mistral/mistral-large-latest",
            "mistral/mistral-large-latest",
            "mistral/mistral-small-latest",
        ),
        prefixes=("mistral/",),
    ),
    "together": Backend(
        name="together",
        description="Together AI",
        required_envs=("TOGETHERAI_API_KEY",),
        defaults=(
            "together_ai/meta-llama/Llama-3.1-70B-Instruct-Turbo",
            "together_ai/meta-llama/Llama-3.1-70B-Instruct-Turbo",
            "together_ai/meta-llama/Llama-3.1-8B-Instruct-Turbo",
        ),
        prefixes=("together_ai/",),
    ),
    "fireworks": Backend(
        name="fireworks",
        description="Fireworks AI",
        required_envs=("FIREWORKS_API_KEY",),
        defaults=(
            "fireworks_ai/accounts/fireworks/models/llama-v3p1-70b-instruct",
            "fireworks_ai/accounts/fireworks/models/llama-v3p1-70b-instruct",
            "fireworks_ai/accounts/fireworks/models/llama-v3p1-8b-instruct",
        ),
        prefixes=("fireworks_ai/",),
    ),
    "xai": Backend(
        name="xai",
        description="xAI Grok via LiteLLM",
        required_envs=("XAI_API_KEY",),
        defaults=("xai/grok-beta", "xai/grok-beta", "xai/grok-beta"),
        prefixes=("xai/",),
    ),
    "cerebras": Backend(
        name="cerebras",
        description="Cerebras inference",
        required_envs=("CEREBRAS_API_KEY",),
        defaults=(
            "cerebras/llama3.1-70b",
            "cerebras/llama3.1-70b",
            "cerebras/llama3.1-8b",
        ),
        prefixes=("cerebras/",),
    ),
    "sambanova": Backend(
        name="sambanova",
        description="SambaNova inference",
        required_envs=("SAMBANOVA_API_KEY",),
        defaults=(
            "sambanova/Meta-Llama-3.1-70B-Instruct",
            "sambanova/Meta-Llama-3.1-70B-Instruct",
            "sambanova/Meta-Llama-3.1-8B-Instruct",
        ),
        prefixes=("sambanova/",),
    ),
    "azure-openai": Backend(
        name="azure-openai",
        description="Azure OpenAI deployment",
        required_envs=("AZURE_API_KEY", "AZURE_API_BASE"),
        defaults=("azure/gpt-4o", "azure/gpt-4o", "azure/gpt-4o-mini"),
        prefixes=("azure/",),
    ),
    "openai-compatible": Backend(
        name="openai-compatible",
        description="Generic OpenAI-compatible API endpoint",
        required_envs=("OPENAI_API_KEY", "OPENAI_API_BASE"),
        defaults=(
            "openai/gpt-4o-mini",
            "openai/gpt-4o-mini",
            "openai/gpt-4o-mini",
        ),
        base_env="OPENAI_API_BASE",
        prefixes=("openai/",),
    ),
    "ollama": Backend(
        name="ollama",
        description="Local Ollama endpoint",
        required_envs=("OLLAMA_BASE_URL",),
        defaults=(settings.local_model, settings.local_model, settings.local_model),
        base_env="OLLAMA_BASE_URL",
        prefixes=("ollama/",),
    ),
}


class LiteLLMProvider(LLMProvider):
    """Multi-provider router backed by LiteLLM."""

    def __init__(self) -> None:
        self._litellm = None
        self._available = False
        try:
            import litellm

            self._litellm = litellm
            self._litellm.set_verbose = False
            self._available = True
        except Exception as exc:
            logger.warning(f"litellm unavailable: {exc}")

    def validate_config(self) -> bool:
        return self._available and bool(self.available_backends())

    def available_backends(self) -> List[str]:
        ordered = self._ordered_configured_backends()
        return [item.name for item in ordered]

    def get_available_models(self) -> List[str]:
        models: List[str] = []
        for backend in self._ordered_configured_backends():
            for role_name in ROLE_NAMES:
                model = self._resolve_model_for_backend(backend, role_name)
                if model:
                    models.append(model)
        return list(dict.fromkeys(models))

    def preferred_provider(self) -> Optional[str]:
        raw = os.getenv("VIKI_PROVIDER", "").strip().lower()
        return raw or None

    def _provider_allow_fallbacks(self) -> bool:
        raw = os.getenv("VIKI_PROVIDER_ALLOW_FALLBACKS", "").strip().lower()
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
        return bool(getattr(settings, "viki_provider_allow_fallbacks", False))

    def _preferred_ollama_model_name(self) -> str:
        explicit = (
            os.getenv("OLLAMA_MODEL", "").strip()
            or str(getattr(settings, "ollama_model", "") or "").strip()
            or settings.local_model.removeprefix("ollama/")
        )
        return explicit or settings.local_model.removeprefix("ollama/")

    def _ollama_status(self):
        return get_ollama_runtime_status(
            allow_pull=False,
            preferred_model=self._preferred_ollama_model_name(),
        )

    def _normalize_ollama_model(self, model_name: str) -> str:
        normalized = model_name.strip()
        if normalized.startswith("ollama/"):
            return normalized
        return f"ollama/{normalized}"

    def model_slots(self) -> Dict[str, str]:
        selected = self._ordered_configured_backends()
        first_backend = selected[0] if selected else None
        slots: Dict[str, str] = {}
        for role_name in ROLE_NAMES:
            if first_backend:
                slots[role_name] = self._resolve_model_for_backend(first_backend, role_name)
            else:
                slots[role_name] = self._global_role_override(role_name) or getattr(settings, f"{'quick' if role_name == 'fast' else role_name}_model")
        return slots

    def diagnostics(self) -> Dict[str, Any]:
        supported = list(BACKENDS)
        preferred = self.preferred_provider()
        warnings: List[str] = []
        if preferred and preferred not in supported:
            warnings.append(
                f"VIKI_PROVIDER={preferred} is not supported. Supported values: {', '.join(supported)}."
            )

        configured = self._ordered_configured_backends()
        all_configured = [backend.name for backend in BACKENDS.values() if self._backend_is_configured(backend)]
        if preferred and preferred in supported and preferred not in [item.name for item in configured]:
            required = ", ".join(BACKENDS[preferred].required_envs)
            warnings.append(
                f"Preferred provider '{preferred}' is not configured. Required environment variables: {required}."
            )
        ollama_status = self._ollama_status()
        if preferred == "ollama" and not ollama_status.reachable:
            warnings.append(ollama_status.error or "Ollama is selected, but the local runtime is not reachable.")
        elif preferred == "ollama" and not ollama_status.selected_model:
            warnings.append(
                f"Ollama is reachable but no coding-capable model is installed yet. Recommended model: {ollama_status.recommended_model}."
            )

        if not configured:
            warnings.append(
                "No live provider credentials detected. Set one provider key or local endpoint before running live tasks."
            )

        matrix: List[Dict[str, Any]] = []
        configured_names = [item.name for item in configured]
        for backend in BACKENDS.values():
            is_ready = self._backend_is_configured(backend)
            matrix.append(
                {
                    "name": backend.name,
                    "status": "configured" if is_ready else "missing",
                    "preferred": backend.name == preferred,
                    "selected": bool(configured_names and configured_names[0] == backend.name),
                    "required_envs": list(backend.required_envs),
                    "base": self._backend_base(backend) or "-",
                    "models": {
                        role_name: self._resolve_model_for_backend(backend, role_name)
                        for role_name in ROLE_NAMES
                    },
                    "description": backend.description,
                }
            )

        hints = [
            "Use VIKI_PROVIDER to pin the preferred backend. Fallbacks stay off by default so the selected provider is the active runtime.",
            "Use VIKI_REASONING_MODEL, VIKI_CODING_MODEL, and VIKI_FAST_MODEL to override the role models across providers.",
            "Use --plain for CI/log-safe output and --force-rich when you want themed transcripts in captured sessions.",
        ]
        if ollama_status.cli_available:
            if ollama_status.selected_model:
                hints.insert(0, f"Ollama local model ready: {ollama_status.selected_model}.")
            elif ollama_status.reachable:
                hints.insert(0, f"Ollama is reachable but needs a coding model. Recommended local pull: {ollama_status.recommended_model}.")
        if "nvidia" in configured_names:
            hints.insert(
                1,
                "NVIDIA is routed through an OpenAI-compatible endpoint internally, so the setup wizard keeps the transport details hidden behind the NVIDIA preset.",
            )
        return {
            "litellm_available": self._available,
            "preferred_provider": preferred,
            "selected_provider": configured_names[0] if configured_names else None,
            "fallback_chain": configured_names,
            "configured_backends": all_configured,
            "model_slots": self.model_slots(),
            "warnings": warnings,
            "hints": hints,
            "matrix": matrix,
        }

    def _ordered_configured_backends(self) -> List[Backend]:
        configured = [backend for backend in BACKENDS.values() if self._backend_is_configured(backend)]
        preferred = self.preferred_provider()
        if preferred:
            selected = [item for item in configured if item.name == preferred]
            if not selected:
                return configured if self._provider_allow_fallbacks() else []
            if not self._provider_allow_fallbacks():
                return selected
            remainder = [item for item in configured if item.name != preferred]
            return selected + remainder
        configured.sort(key=lambda item: (self._auto_select_priority(item), item.name))
        return configured

    def _auto_select_priority(self, backend: Backend) -> int:
        base = os.getenv("OPENAI_API_BASE", "").strip()
        explicit = {
            "dashscope": bool(os.getenv("DASHSCOPE_API_KEY")),
            "openrouter": bool(os.getenv("OPENROUTER_API_KEY")),
            "openai-compatible": bool(
                os.getenv("OPENAI_API_KEY")
                and base
                and "api.openai.com" not in base
                and "integrate.api.nvidia.com" not in base
            ),
            "openai": bool(os.getenv("OPENAI_API_KEY") and (not base or "api.openai.com" in base)),
            "nvidia": bool(os.getenv("NVIDIA_API_KEY")) or bool(
                os.getenv("OPENAI_API_KEY") and "integrate.api.nvidia.com" in base
            ),
            "ollama": bool(os.getenv("OLLAMA_BASE_URL")),
        }
        if explicit.get(backend.name):
            return 0
        if backend.name == "ollama":
            return 1
        return 2

    def _backend_is_configured(self, backend: Backend) -> bool:
        if backend.name == "openai":
            key = os.getenv("OPENAI_API_KEY")
            base = os.getenv("OPENAI_API_BASE")
            return bool(key and (not base or "api.openai.com" in base))
        if backend.name == "ollama":
            status = self._ollama_status()
            base = os.getenv("OLLAMA_BASE_URL") or str(getattr(settings, "ollama_base_url", "") or "").strip() or DEFAULT_OLLAMA_BASE_URL
            explicit_model = self._preferred_ollama_model_name()
            if explicit_model and base and not status.cli_available:
                return True
            return bool(status.reachable and (status.selected_model or explicit_model))
        if backend.name == "nvidia":
            key = os.getenv("NVIDIA_API_KEY") or os.getenv("OPENAI_API_KEY")
            base = os.getenv("NVIDIA_API_BASE") or os.getenv("OPENAI_API_BASE") or backend.base_default
            return bool(key and base and "integrate.api.nvidia.com" in base)
        if backend.name == "openai-compatible":
            key = os.getenv("OPENAI_API_KEY")
            base = os.getenv("OPENAI_API_BASE")
            return bool(key and base and "api.openai.com" not in base and "integrate.api.nvidia.com" not in base)
        return all(os.getenv(env_name) for env_name in backend.required_envs)

    def _backend_base(self, backend: Backend) -> Optional[str]:
        if backend.name == "ollama":
            configured = os.getenv("OLLAMA_BASE_URL") or str(getattr(settings, "ollama_base_url", "") or "").strip()
            if configured:
                return configured
            status = self._ollama_status()
            return status.base_url or DEFAULT_OLLAMA_BASE_URL
        if backend.name == "nvidia":
            return os.getenv("NVIDIA_API_BASE") or os.getenv("OPENAI_API_BASE") or backend.base_default
        if backend.base_env:
            return os.getenv(backend.base_env) or backend.base_default
        return None

    def _global_role_override(self, role_name: str) -> Optional[str]:
        env_name = {
            "reasoning": "VIKI_REASONING_MODEL",
            "coding": "VIKI_CODING_MODEL",
            "fast": "VIKI_FAST_MODEL",
        }[role_name]
        value = os.getenv(env_name, "").strip()
        return value or None

    def _resolve_model_for_backend(self, backend: Backend, role_name: str) -> str:
        override = self._global_role_override(role_name)
        if override:
            return override

        if backend.name == "openai-compatible":
            compat = os.getenv("OPENAI_COMPAT_MODEL", "").strip()
            return compat or backend.defaults[ROLE_NAMES.index(role_name)]
        if backend.name == "nvidia":
            nvidia_model = os.getenv("NVIDIA_MODEL", "").strip()
            compat = os.getenv("OPENAI_COMPAT_MODEL", "").strip()
            return nvidia_model or compat or backend.defaults[ROLE_NAMES.index(role_name)]
        if backend.name == "azure-openai":
            azure_model = os.getenv("AZURE_MODEL", "").strip()
            return azure_model or backend.defaults[ROLE_NAMES.index(role_name)]
        if backend.name == "ollama":
            ollama_model = os.getenv("OLLAMA_MODEL", "").strip() or str(getattr(settings, "ollama_model", "") or "").strip()
            if ollama_model:
                return self._normalize_ollama_model(ollama_model)
            status = self._ollama_status()
            selected = status.selected_model or status.recommended_model
            return self._normalize_ollama_model(selected)
        return backend.defaults[ROLE_NAMES.index(role_name)]

    def _explicit_model_candidates(self, model: str) -> List[ResolvedCandidate]:
        normalized = model.strip()
        candidates: List[ResolvedCandidate] = []
        for backend in self._ordered_configured_backends():
            if any(normalized.startswith(prefix) for prefix in backend.prefixes):
                candidates.append(ResolvedCandidate(backend=backend.name, model=normalized, kwargs=self._candidate_kwargs(backend)))
        if candidates:
            return candidates
        for backend in self._ordered_configured_backends():
            candidates.append(ResolvedCandidate(backend=backend.name, model=normalized, kwargs=self._candidate_kwargs(backend)))
        return candidates

    def _resolve_candidates(self, model: Optional[str]) -> List[ResolvedCandidate]:
        if model and model not in ROLE_NAMES:
            return self._explicit_model_candidates(model)

        requested = model or "coding"
        candidates: List[ResolvedCandidate] = []
        for backend in self._ordered_configured_backends():
            resolved = self._resolve_model_for_backend(backend, requested)
            candidates.append(ResolvedCandidate(backend=backend.name, model=resolved, kwargs=self._candidate_kwargs(backend)))

        if not candidates:
            if self.preferred_provider() and not self._provider_allow_fallbacks():
                return []
            fallback_model = self._global_role_override(requested) or {
                "reasoning": settings.reasoning_model,
                "coding": settings.coding_model,
                "fast": settings.quick_model,
            }[requested]
            candidates.append(ResolvedCandidate(backend="default", model=fallback_model, kwargs={}))
        deduped: List[ResolvedCandidate] = []
        seen: set[tuple[str, str, tuple[tuple[str, Any], ...]]] = set()
        for candidate in candidates:
            signature = (
                candidate.backend,
                candidate.model,
                tuple(sorted(candidate.kwargs.items())),
            )
            if signature in seen:
                continue
            seen.add(signature)
            deduped.append(candidate)
        return deduped

    def _candidate_kwargs(self, backend: Backend) -> Dict[str, Any]:
        if backend.name == "dashscope":
            return {
                "api_key": os.getenv("DASHSCOPE_API_KEY"),
                "api_base": self._backend_base(backend),
            }
        if backend.name == "openrouter":
            return {
                "api_key": os.getenv("OPENROUTER_API_KEY"),
                "api_base": self._backend_base(backend),
            }
        if backend.name == "openai-compatible":
            return {
                "api_key": os.getenv("OPENAI_API_KEY"),
                "api_base": self._backend_base(backend),
            }
        if backend.name == "nvidia":
            return {
                "api_key": os.getenv("NVIDIA_API_KEY") or os.getenv("OPENAI_API_KEY"),
                "api_base": self._backend_base(backend),
            }
        if backend.name == "openai":
            kwargs: Dict[str, Any] = {"api_key": os.getenv("OPENAI_API_KEY")}
            base = self._backend_base(backend)
            if base:
                kwargs["api_base"] = base
            return kwargs
        if backend.name == "azure-openai":
            kwargs = {
                "api_key": os.getenv("AZURE_API_KEY"),
                "api_base": os.getenv("AZURE_API_BASE"),
            }
            api_version = os.getenv("AZURE_API_VERSION", "").strip()
            if api_version:
                kwargs["api_version"] = api_version
            return kwargs
        if backend.name == "ollama":
            return {"api_base": self._backend_base(backend) or DEFAULT_OLLAMA_BASE_URL}

        if backend.required_envs:
            return {"api_key": os.getenv(backend.required_envs[0])}
        return {}

    async def complete(self, model: Optional[str], messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        if not self._available:
            raise RuntimeError("litellm is not installed")

        candidates = self._resolve_candidates(model)
        errors: List[str] = []
        for candidate in candidates:
            try:
                response = await self._litellm.acompletion(
                    model=candidate.model,
                    messages=messages,
                    temperature=kwargs.get("temperature", 0.1),
                    max_tokens=kwargs.get("max_tokens", 4000),
                    timeout=kwargs.get("timeout", 120),
                    **candidate.kwargs,
                )
                usage = getattr(response, "usage", None)
                return {
                    "content": response.choices[0].message.content,
                    "usage": {
                        "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                        "completion_tokens": getattr(usage, "completion_tokens", 0),
                        "total_tokens": getattr(usage, "total_tokens", 0),
                    },
                    "model": candidate.model,
                    "provider": candidate.backend,
                    "attempts": [item.model for item in candidates],
                }
            except Exception as exc:
                logger.warning(f"provider attempt failed for {candidate.backend}:{candidate.model}: {exc}")
                errors.append(f"{candidate.backend}:{candidate.model} -> {exc}")
        raise RuntimeError(
            "All provider attempts failed. "
            + (" | ".join(errors[:4]) if errors else "No provider candidates were available.")
        )
