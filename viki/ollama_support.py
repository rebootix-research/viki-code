from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Iterable, Sequence


DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_PULL_MODEL = "qwen2.5-coder:7b"


@dataclass(frozen=True)
class OllamaRuntimeStatus:
    cli_available: bool
    reachable: bool
    base_url: str
    models: tuple[str, ...]
    selected_model: str | None
    recommended_model: str
    pulled_model: bool = False
    error: str | None = None


def _run_ollama(args: Sequence[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ollama", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def ollama_cli_available() -> bool:
    return bool(shutil.which("ollama"))


def parse_ollama_list(output: str) -> list[str]:
    models: list[str] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("name"):
            continue
        parts = re.split(r"\s{2,}", line)
        if parts and parts[0]:
            models.append(parts[0].strip())
    return models


def _size_bias(model_name: str) -> int:
    lowered = model_name.lower()
    if any(token in lowered for token in ["7b", "8b"]):
        return 16
    if "14b" in lowered:
        return 14
    if "32b" in lowered:
        return 8
    if any(token in lowered for token in ["1.5b", "3b"]):
        return 4
    if any(token in lowered for token in ["70b", "72b"]):
        return 2
    return 0


def choose_best_ollama_model(models: Iterable[str]) -> str | None:
    ranked: list[tuple[int, str]] = []
    for raw in models:
        model = raw.strip()
        if not model:
            continue
        lowered = model.lower()
        score = 0
        keyword_scores = [
            ("qwen2.5-coder", 130),
            ("qwen3-coder", 126),
            ("deepseek-coder", 122),
            ("deepseek-r1", 118),
            ("codellama", 112),
            ("starcoder2", 108),
            ("qwen2.5", 100),
            ("qwen3", 96),
            ("llama3.3", 88),
            ("llama3.2", 84),
            ("llama3.1", 82),
            ("phi4", 76),
            ("mistral", 72),
        ]
        for token, value in keyword_scores:
            if token in lowered:
                score = max(score, value)
        score += _size_bias(lowered)
        if "coder" in lowered:
            score += 6
        if score:
            ranked.append((score, model))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return ranked[0][1]


def get_ollama_runtime_status(*, allow_pull: bool = False, preferred_model: str | None = None) -> OllamaRuntimeStatus:
    base_url = DEFAULT_OLLAMA_BASE_URL
    recommended = preferred_model or DEFAULT_OLLAMA_PULL_MODEL
    if not ollama_cli_available():
        return OllamaRuntimeStatus(
            cli_available=False,
            reachable=False,
            base_url=base_url,
            models=(),
            selected_model=None,
            recommended_model=recommended,
            error="Ollama CLI is not installed.",
        )

    listed = _run_ollama(["list"], timeout=180)
    if listed.returncode != 0:
        return OllamaRuntimeStatus(
            cli_available=True,
            reachable=False,
            base_url=base_url,
            models=(),
            selected_model=None,
            recommended_model=recommended,
            error=(listed.stderr or listed.stdout).strip() or "Ollama is installed but the local runtime is not reachable.",
        )

    models = tuple(parse_ollama_list(listed.stdout))
    selected = choose_best_ollama_model(models)
    if selected or not allow_pull:
        return OllamaRuntimeStatus(
            cli_available=True,
            reachable=True,
            base_url=base_url,
            models=models,
            selected_model=selected,
            recommended_model=recommended,
        )

    pulled = _run_ollama(["pull", recommended], timeout=7200)
    if pulled.returncode != 0:
        return OllamaRuntimeStatus(
            cli_available=True,
            reachable=True,
            base_url=base_url,
            models=models,
            selected_model=None,
            recommended_model=recommended,
            error=(pulled.stderr or pulled.stdout).strip() or f"Failed to pull {recommended}.",
        )

    refreshed = _run_ollama(["list"], timeout=180)
    refreshed_models = tuple(parse_ollama_list(refreshed.stdout)) if refreshed.returncode == 0 else models
    selected = choose_best_ollama_model(refreshed_models)
    return OllamaRuntimeStatus(
        cli_available=True,
        reachable=refreshed.returncode == 0,
        base_url=base_url,
        models=refreshed_models,
        selected_model=selected,
        recommended_model=recommended,
        pulled_model=True,
        error=None if refreshed.returncode == 0 else (refreshed.stderr or refreshed.stdout).strip(),
    )
