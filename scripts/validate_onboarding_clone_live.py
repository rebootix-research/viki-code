from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from viki.infrastructure.security import SecurityScanner
from viki.onboarding import iter_provider_presets
from viki.platforms import PlatformSupport

PROVIDER_ENV_PRIORITY = [
    ("nvidia", ["NVIDIA_API_KEY"], ["NVIDIA_API_KEY", "NVIDIA_API_BASE", "OPENAI_COMPAT_MODEL", "VIKI_PROVIDER", "VIKI_REASONING_MODEL", "VIKI_CODING_MODEL", "VIKI_FAST_MODEL"]),
    ("dashscope", ["DASHSCOPE_API_KEY"], ["DASHSCOPE_API_KEY", "DASHSCOPE_API_BASE", "VIKI_PROVIDER", "VIKI_REASONING_MODEL", "VIKI_CODING_MODEL", "VIKI_FAST_MODEL"]),
    ("openrouter", ["OPENROUTER_API_KEY"], ["OPENROUTER_API_KEY", "OPENROUTER_API_BASE", "VIKI_PROVIDER", "VIKI_REASONING_MODEL", "VIKI_CODING_MODEL", "VIKI_FAST_MODEL"]),
    ("openai-compatible", ["OPENAI_API_KEY", "OPENAI_API_BASE"], ["OPENAI_API_KEY", "OPENAI_API_BASE", "OPENAI_COMPAT_MODEL", "VIKI_PROVIDER", "VIKI_REASONING_MODEL", "VIKI_CODING_MODEL", "VIKI_FAST_MODEL"]),
    ("openai", ["OPENAI_API_KEY"], ["OPENAI_API_KEY", "VIKI_PROVIDER", "VIKI_REASONING_MODEL", "VIKI_CODING_MODEL", "VIKI_FAST_MODEL"]),
    ("anthropic", ["ANTHROPIC_API_KEY"], ["ANTHROPIC_API_KEY", "VIKI_PROVIDER", "VIKI_REASONING_MODEL", "VIKI_CODING_MODEL", "VIKI_FAST_MODEL"]),
    ("ollama", ["OLLAMA_BASE_URL"], ["OLLAMA_BASE_URL", "OLLAMA_MODEL", "VIKI_PROVIDER", "VIKI_REASONING_MODEL", "VIKI_CODING_MODEL", "VIKI_FAST_MODEL"]),
]
KNOWN_PROVIDER_SECRET_KEYS = {
    "DASHSCOPE_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "DEEPSEEK_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "NVIDIA_API_KEY",
    "TOGETHERAI_API_KEY",
    "FIREWORKS_API_KEY",
    "XAI_API_KEY",
    "CEREBRAS_API_KEY",
    "SAMBANOVA_API_KEY",
    "AZURE_API_KEY",
}


def detect_live_provider(env: dict[str, str]) -> dict[str, object]:
    nvidia_key = env.get("NVIDIA_API_KEY") or env.get("OPENAI_API_KEY")
    nvidia_base = env.get("NVIDIA_API_BASE") or env.get("OPENAI_API_BASE") or ""
    if nvidia_key and "integrate.api.nvidia.com" in nvidia_base:
        forwarded_keys = [
            key
            for key in [
                "NVIDIA_API_KEY",
                "NVIDIA_API_BASE",
                "OPENAI_API_KEY",
                "OPENAI_API_BASE",
                "OPENAI_COMPAT_MODEL",
                "VIKI_PROVIDER",
                "VIKI_REASONING_MODEL",
                "VIKI_CODING_MODEL",
                "VIKI_FAST_MODEL",
            ]
            if env.get(key)
        ]
        return {
            "provider": "nvidia",
            "forwarded_keys": forwarded_keys,
        }
    preferred = env.get("VIKI_PROVIDER", "").strip().lower()
    if preferred:
        for name, required, keys in PROVIDER_ENV_PRIORITY:
            if name == preferred and all(env.get(key) for key in required):
                return {"provider": name, "forwarded_keys": [key for key in keys if env.get(key)]}
    for name, required, keys in PROVIDER_ENV_PRIORITY:
        if required and all(env.get(key) for key in required):
            return {"provider": name, "forwarded_keys": [key for key in keys if env.get(key)]}
    return {"provider": None, "forwarded_keys": []}


def isolate_provider_env(env: dict[str, str], detected: dict[str, object]) -> dict[str, str]:
    isolated = env.copy()
    forwarded = set(detected.get("forwarded_keys", []))
    for key in KNOWN_PROVIDER_SECRET_KEYS:
        if key not in forwarded:
            isolated.pop(key, None)
    if detected.get("provider"):
        isolated["VIKI_PROVIDER"] = str(detected["provider"])
    if detected.get("provider") == "dashscope":
        isolated.setdefault("DASHSCOPE_API_BASE", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
    if detected.get("provider") == "openrouter":
        isolated.setdefault("OPENROUTER_API_BASE", "https://openrouter.ai/api/v1")
    if detected.get("provider") == "nvidia":
        isolated.setdefault("NVIDIA_API_KEY", isolated.get("OPENAI_API_KEY", ""))
        isolated.setdefault("NVIDIA_API_BASE", isolated.get("OPENAI_API_BASE", "https://integrate.api.nvidia.com/v1"))
        isolated.pop("OPENAI_API_KEY", None)
        isolated.pop("OPENAI_API_BASE", None)
        isolated["VIKI_PROVIDER"] = "nvidia"
    return isolated


def setup_wizard_input(provider_slug: str) -> str:
    presets = list(iter_provider_presets())
    try:
        provider_index = next(index for index, preset in enumerate(presets, start=1) if preset.slug == provider_slug)
    except StopIteration as exc:
        raise RuntimeError(f"Unsupported provider slug for onboarding validation: {provider_slug}") from exc
    return f"{provider_index}\n1\ny\n\n1\n1\n1\nn\nn\n"


def bugfix_prompt_variants() -> list[str]:
    return [
        "Fix the broken calculation in this repository and make the tests pass.",
        "The multiply function in this repository is wrong. Repair the implementation so multiplication is correct and run the relevant test before you finish.",
    ]


def remove_tree(path: Path) -> None:
    def _handle_remove_readonly(func, target, exc_info):  # pragma: no cover - platform dependent
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if path.exists():
        shutil.rmtree(path, onerror=_handle_remove_readonly)


def parse_session_id(text: str) -> str | None:
    match = re.search(r"(\d{8}-\d{6})", text)
    return match.group(1) if match else None


def powershell_command(command: str) -> list[str]:
    shell = shutil.which("powershell") or shutil.which("pwsh") or "powershell"
    return [shell, "-NoProfile", "-Command", command]


def run_powershell(
    command: str,
    cwd: Path,
    env: dict[str, str],
    security: SecurityScanner,
    timeout: int = 1800,
    input_text: str | None = None,
) -> dict[str, object]:
    completed = subprocess.run(
        powershell_command(command),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        input=input_text,
    )
    return {
        "command": command,
        "cwd": str(cwd),
        "returncode": completed.returncode,
        "stdout": security.redact_text(completed.stdout),
        "stderr": security.redact_text(completed.stderr),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the GitHub onboarding flow from a fresh clone in PowerShell.")
    parser.add_argument("--repo-url", default="https://github.com/rebootix-research/viki-code.git")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--output", default="LIVE_RUN_RESULTS/github_clone_onboarding")
    args = parser.parse_args()

    output = Path(args.output).resolve()
    remove_tree(output)
    output.mkdir(parents=True, exist_ok=True)

    security = SecurityScanner()
    detected = detect_live_provider(os.environ.copy())
    if not detected["provider"]:
        raise RuntimeError("No live provider environment variables are available in the current session.")

    env = isolate_provider_env(os.environ.copy(), detected)
    config_home = output / "config-home"
    env["VIKI_CONFIG_HOME"] = str(config_home)

    clone_dir = output / "viki-code"
    commands: list[dict[str, object]] = []

    commands.append(
        run_powershell(
            f"git clone --depth 1 --branch {args.branch} {args.repo_url} '{clone_dir}'",
            output,
            env,
            security,
            timeout=1800,
        )
    )
    commands.append(run_powershell("python scripts/install.py --path .", clone_dir, env, security, timeout=2400))

    user_bin = PlatformSupport.user_bin_dir()
    env["PATH"] = str(user_bin) + os.pathsep + env.get("PATH", "")
    commands.append(run_powershell("$cmd = Get-Command viki -ErrorAction SilentlyContinue; if (-not $cmd) { exit 1 }; $cmd.Source", clone_dir, env, security))
    commands.append(run_powershell("viki --plain version", clone_dir, env, security))
    commands.append(run_powershell("viki --plain providers", clone_dir, env, security))

    setup_input = setup_wizard_input(str(detected["provider"]))
    commands.append(run_powershell("viki setup .", clone_dir, env, security, timeout=1800, input_text=setup_input))
    commands.append(run_powershell("viki --plain doctor .", clone_dir, env, security))

    bugfix_repo = output / "generic_bugfix_repo"
    shutil.copytree(clone_dir / "benchmarks" / "public" / "generic_bugfix" / "fixture", bugfix_repo)

    prompt_first_result = run_powershell("viki --force-rich --theme premium", bugfix_repo, env, security, timeout=1800, input_text="\n")
    commands.append(prompt_first_result)

    live_result: dict[str, object] | None = None
    session_id: str | None = None
    retry_used = False
    for prompt in bugfix_prompt_variants():
        candidate = run_powershell(
            f"viki --force-rich --theme premium run \"{prompt}\" --path .",
            bugfix_repo,
            env,
            security,
            timeout=3600,
        )
        commands.append(candidate)
        live_result = candidate
        session_id = parse_session_id(str(candidate["stdout"]))
        pytest_candidate = run_powershell("python -m pytest --rootdir . tests/test_calculator.py -q", bugfix_repo, env, security, timeout=600)
        commands.append(pytest_candidate)
        calculator_text = (bugfix_repo / "app" / "calculator.py").read_text(encoding="utf-8")
        if candidate["returncode"] == 0 and "return a * b" in calculator_text and pytest_candidate["returncode"] == 0:
            break
        retry_used = True
    assert live_result is not None
    if session_id:
        commands.append(run_powershell(f"viki --force-rich --theme premium diff {session_id} --path '{bugfix_repo}' --rendered", bugfix_repo, env, security, timeout=600))

    config_saved = config_home.joinpath("config.env").exists()
    remove_tree(config_home)
    calculator_text = (bugfix_repo / "app" / "calculator.py").read_text(encoding="utf-8")
    latest_pytest = commands[-2] if session_id else commands[-1]

    summary = {
        "repo_url": args.repo_url,
        "branch": args.branch,
        "provider": detected["provider"],
        "clone_ok": commands[0]["returncode"] == 0,
        "install_ok": commands[1]["returncode"] == 0,
        "command_on_path_ok": commands[2]["returncode"] == 0,
        "version_ok": commands[3]["returncode"] == 0,
        "providers_ok": commands[4]["returncode"] == 0,
        "setup_wizard_ok": commands[5]["returncode"] == 0 and config_saved,
        "doctor_ok": commands[6]["returncode"] == 0,
        "prompt_first_ok": prompt_first_result["returncode"] == 0 and "Prompt-First Console" in str(prompt_first_result["stdout"]),
        "live_bugfix_ok": live_result["returncode"] == 0 and "return a * b" in calculator_text and latest_pytest["returncode"] == 0,
        "rendered_diff_ok": bool(session_id) and any(" --rendered" in str(item["command"]) and item["returncode"] == 0 for item in commands),
        "pytest_ok": latest_pytest["returncode"] == 0,
        "telegram_prompt_visible": "Telegram" in str(commands[5]["stdout"]),
        "whatsapp_prompt_visible": "WhatsApp" in str(commands[5]["stdout"]),
        "session_id": session_id,
        "config_home": str(config_home),
        "config_home_removed": not config_home.exists(),
        "bugfix_retry_used": retry_used,
        "user_bin": str(user_bin),
    }

    (output / "commands.json").write_text(json.dumps(commands, indent=2) + "\n", encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
