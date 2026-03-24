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
from viki.ollama_support import DEFAULT_OLLAMA_BASE_URL, get_ollama_runtime_status
from viki.platforms import PlatformSupport

PROVIDER_ENV_PRIORITY = [
    ("ollama", ["OLLAMA_BASE_URL"], ["OLLAMA_BASE_URL", "OLLAMA_MODEL", "VIKI_PROVIDER", "VIKI_REASONING_MODEL", "VIKI_CODING_MODEL", "VIKI_FAST_MODEL"]),
    ("dashscope", ["DASHSCOPE_API_KEY"], ["DASHSCOPE_API_KEY", "DASHSCOPE_API_BASE", "VIKI_PROVIDER", "VIKI_REASONING_MODEL", "VIKI_CODING_MODEL", "VIKI_FAST_MODEL"]),
    ("openrouter", ["OPENROUTER_API_KEY"], ["OPENROUTER_API_KEY", "OPENROUTER_API_BASE", "VIKI_PROVIDER", "VIKI_REASONING_MODEL", "VIKI_CODING_MODEL", "VIKI_FAST_MODEL"]),
    ("openai-compatible", ["OPENAI_API_KEY", "OPENAI_API_BASE"], ["OPENAI_API_KEY", "OPENAI_API_BASE", "OPENAI_COMPAT_MODEL", "VIKI_PROVIDER", "VIKI_REASONING_MODEL", "VIKI_CODING_MODEL", "VIKI_FAST_MODEL"]),
    ("openai", ["OPENAI_API_KEY"], ["OPENAI_API_KEY", "VIKI_PROVIDER", "VIKI_REASONING_MODEL", "VIKI_CODING_MODEL", "VIKI_FAST_MODEL"]),
    ("anthropic", ["ANTHROPIC_API_KEY"], ["ANTHROPIC_API_KEY", "VIKI_PROVIDER", "VIKI_REASONING_MODEL", "VIKI_CODING_MODEL", "VIKI_FAST_MODEL"]),
    ("nvidia", ["NVIDIA_API_KEY"], ["NVIDIA_API_KEY", "NVIDIA_API_BASE", "VIKI_PROVIDER", "VIKI_REASONING_MODEL", "VIKI_CODING_MODEL", "VIKI_FAST_MODEL"]),
]
KNOWN_PROVIDER_SECRET_KEYS = {
    "DASHSCOPE_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "NVIDIA_API_KEY",
}


def detect_live_provider(env: dict[str, str]) -> dict[str, object]:
    ollama_status = get_ollama_runtime_status(allow_pull=False)
    if ollama_status.cli_available and ollama_status.reachable:
        selected_model = ollama_status.selected_model or ollama_status.recommended_model
        return {
            "provider": "ollama",
            "forwarded_keys": ["OLLAMA_BASE_URL", "OLLAMA_MODEL"],
            "ollama_model": selected_model,
        }
    preferred = (env.get("VIKI_PROVIDER") or "").strip().lower()
    if preferred:
        for name, required, keys in PROVIDER_ENV_PRIORITY:
            if name == preferred and all(env.get(key) for key in required):
                return {"provider": name, "forwarded_keys": [key for key in keys if env.get(key)]}
    for name, required, keys in PROVIDER_ENV_PRIORITY:
        if all(env.get(key) for key in required):
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
    isolated["VIKI_PROVIDER_ALLOW_FALLBACKS"] = "false"
    if detected.get("provider") == "dashscope":
        isolated.setdefault("DASHSCOPE_API_BASE", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
    if detected.get("provider") == "openrouter":
        isolated.setdefault("OPENROUTER_API_BASE", "https://openrouter.ai/api/v1")
    if detected.get("provider") == "ollama":
        isolated["OLLAMA_BASE_URL"] = str(env.get("OLLAMA_BASE_URL") or DEFAULT_OLLAMA_BASE_URL)
        if detected.get("ollama_model"):
            isolated["OLLAMA_MODEL"] = str(detected["ollama_model"])
    return isolated


def setup_wizard_input(provider_slug: str) -> str:
    provider_index_map = {
        "dashscope": 1,
        "openai": 2,
        "openrouter": 3,
        "anthropic": 4,
        "azure-openai": 5,
        "nvidia": 6,
        "openai-compatible": 7,
        "ollama": 8,
    }
    provider_index = provider_index_map.get(provider_slug, 1)
    if provider_slug == "ollama":
        status = get_ollama_runtime_status(allow_pull=False)
        if status.cli_available and status.reachable and not status.selected_model:
            return f"{provider_index}\n1\n\ny\n1\n1\n1\nn\nn\n"
        if status.cli_available and status.reachable:
            return f"{provider_index}\n1\n\n1\n1\n1\nn\nn\n"
        return f"{provider_index}\n1\n\n{status.recommended_model}\n1\n1\n1\nn\nn\n"
    return f"{provider_index}\n1\ny\n\n1\n1\n1\nn\nn\n"


def bugfix_prompt_variants() -> list[str]:
    return [
        "Fix the broken calculation in this repository so multiply returns correct results, then run the relevant tests.",
        "A multiplication helper is wrong in this repository. Repair it so multiply(3, 4) returns 12 and run the relevant test before you finish.",
    ]


def refactor_prompt_variants() -> list[str]:
    return [
        "Refactor the public auth naming in this repository so the account normalization helper is named normalize_account, keep behavior the same, and run the relevant tests.",
        "There is an auth naming inconsistency in this repository. Rename the public helper to normalize_account, update callers, and run the relevant tests.",
    ]


def remove_tree(path: Path) -> None:
    def _handle_remove_readonly(func, target, exc_info):  # pragma: no cover - platform dependent
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if path.exists():
        shutil.rmtree(path, onerror=_handle_remove_readonly)


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


def parse_session_id(text: str) -> str | None:
    match = re.search(r"(\d{8}-\d{6})", text)
    return match.group(1) if match else None


def extract_provider_failure_text(command_result: dict[str, object]) -> str | None:
    combined = "\n".join(
        part for part in (str(command_result.get("stdout", "")), str(command_result.get("stderr", ""))) if part.strip()
    )
    for marker in (
        "Incorrect API key provided",
        "Authorization failed",
        "exceeded your current quota",
        "All provider attempts failed.",
        "provider attempt failed",
    ):
        if marker in combined:
            for line in combined.splitlines():
                if marker in line:
                    return line.strip()[:400]
            return marker
    return None


def secret_match_count(root: Path, env: dict[str, str], forwarded_keys: list[str]) -> int:
    values = [
        env.get(key, "")
        for key in forwarded_keys
        if key in KNOWN_PROVIDER_SECRET_KEYS and env.get(key)
    ]
    if not values:
        return 0
    count = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for value in values:
            if value and value in text:
                count += 1
    return count


def read_config_summary(config_home: Path) -> dict[str, object]:
    config_path = config_home / "config.env"
    if not config_path.exists():
        return {"exists": False}
    payload: dict[str, str] = {}
    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        payload[key.strip()] = value.strip().strip("\"'")
    return {
        "exists": True,
        "provider": payload.get("VIKI_PROVIDER"),
        "allow_fallbacks": payload.get("VIKI_PROVIDER_ALLOW_FALLBACKS"),
        "ollama_model": payload.get("OLLAMA_MODEL"),
        "has_dashscope_key": "DASHSCOPE_API_KEY" in payload,
        "has_openai_key": "OPENAI_API_KEY" in payload,
        "has_nvidia_key": "NVIDIA_API_KEY" in payload,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the connected VIKI product flow from a fresh GitHub clone.")
    parser.add_argument("--repo-url", default="https://github.com/rebootix-research/viki-code.git")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--output", default="C:/Users/Nabeel Saleem/Documents/Playground/viki_connected_product_validation")
    args = parser.parse_args()

    output = Path(args.output).resolve()
    remove_tree(output)
    output.mkdir(parents=True, exist_ok=True)

    security = SecurityScanner()
    detected = detect_live_provider(os.environ.copy())
    if not detected["provider"]:
        raise RuntimeError("No live provider environment variables are available in the current session.")

    env = isolate_provider_env(os.environ.copy(), detected)
    env["VIKI_PROVIDER"] = str(detected["provider"])
    config_home = output / "config-home"
    env["VIKI_CONFIG_HOME"] = str(config_home)

    clone_dir = output / "viki-code"
    bugfix_repo = output / "generic_bugfix_repo"
    refactor_repo = output / "generic_refactor_repo"
    managed_clone_root = output / "managed-workspaces"
    commands: list[dict[str, object]] = []

    commands.append(run_powershell(f"git clone --depth 1 --branch {args.branch} {args.repo_url} '{clone_dir}'", output, env, security, timeout=1800))
    commands.append(run_powershell("python scripts/install.py --path .", clone_dir, env, security, timeout=2400))

    user_bin = PlatformSupport.user_bin_dir()
    env["PATH"] = str(user_bin) + os.pathsep + env.get("PATH", "")

    commands.append(run_powershell("viki --plain version", clone_dir, env, security))
    commands.append(run_powershell("viki --plain github status", clone_dir, env, security))
    commands.append(run_powershell("viki --plain github repos --limit 5", clone_dir, env, security, timeout=600))
    commands.append(run_powershell("viki setup .", clone_dir, env, security, timeout=1800, input_text=setup_wizard_input(str(detected["provider"]))))
    commands.append(run_powershell("viki --plain doctor .", clone_dir, env, security))

    shutil.copytree(clone_dir / "benchmarks" / "public" / "generic_bugfix" / "fixture", bugfix_repo)
    shutil.copytree(clone_dir / "benchmarks" / "public" / "generic_refactor" / "fixture", refactor_repo)

    commands.append(run_powershell(f"viki --plain workspaces use '{bugfix_repo}'", clone_dir, env, security))
    commands.append(run_powershell("viki --plain workspaces list", clone_dir, env, security))
    commands.append(run_powershell(f"viki --plain github clone rebootix-research/viki-code --destination '{managed_clone_root}'", clone_dir, env, security, timeout=2400))
    commands.append(run_powershell("viki --force-rich --theme premium", output, env, security, timeout=900, input_text="\n"))

    live_bugfix: dict[str, object] | None = None
    bugfix_pytest: dict[str, object] | None = None
    bugfix_session: str | None = None
    for prompt in bugfix_prompt_variants():
        candidate = run_powershell(
            f"viki --force-rich --theme premium run \"{prompt}\" --path '{bugfix_repo}'",
            clone_dir,
            env,
            security,
            timeout=3600,
        )
        commands.append(candidate)
        live_bugfix = candidate
        bugfix_session = parse_session_id(str(candidate["stdout"]))
        pytest_candidate = run_powershell("python -m pytest --rootdir . tests/test_calculator.py -q", bugfix_repo, env, security, timeout=600)
        commands.append(pytest_candidate)
        bugfix_pytest = pytest_candidate
        calculator_text = (bugfix_repo / "app" / "calculator.py").read_text(encoding="utf-8")
        if candidate["returncode"] == 0 and "return a * b" in calculator_text and pytest_candidate["returncode"] == 0:
            break
    assert live_bugfix is not None
    assert bugfix_pytest is not None

    if bugfix_session:
        commands.append(run_powershell(f"viki --plain sessions list '{bugfix_repo}'", clone_dir, env, security))
        commands.append(run_powershell(f"viki --plain sessions continue {bugfix_session} --path '{bugfix_repo}'", clone_dir, env, security, input_text="\n"))
        commands.append(run_powershell(f"viki --force-rich --theme premium diff {bugfix_session} --path '{bugfix_repo}' --rendered", clone_dir, env, security))

    live_refactor: dict[str, object] | None = None
    refactor_pytest: dict[str, object] | None = None
    for prompt in refactor_prompt_variants():
        candidate = run_powershell(
            f"viki --plain run \"{prompt}\" --path '{refactor_repo}'",
            clone_dir,
            env,
            security,
            timeout=3600,
        )
        commands.append(candidate)
        live_refactor = candidate
        pytest_candidate = run_powershell("python -m pytest --rootdir . tests/test_service.py -q", refactor_repo, env, security, timeout=600)
        commands.append(pytest_candidate)
        refactor_pytest = pytest_candidate
        auth_text = (refactor_repo / "packages" / "shared" / "auth.py").read_text(encoding="utf-8")
        service_text = (refactor_repo / "apps" / "api" / "service.py").read_text(encoding="utf-8")
        if candidate["returncode"] == 0 and "def normalize_account" in auth_text and "normalize_account" in service_text and pytest_candidate["returncode"] == 0:
            break
    assert live_refactor is not None
    assert refactor_pytest is not None
    home_shell_output = str(commands[10]["stdout"])
    config_summary = read_config_summary(config_home)
    remove_tree(config_home)

    calculator_text = (bugfix_repo / "app" / "calculator.py").read_text(encoding="utf-8")
    auth_text = (refactor_repo / "packages" / "shared" / "auth.py").read_text(encoding="utf-8")
    service_text = (refactor_repo / "apps" / "api" / "service.py").read_text(encoding="utf-8")
    bugfix_error = extract_provider_failure_text(live_bugfix)
    refactor_error = extract_provider_failure_text(live_refactor)

    summary = {
        "repo_url": args.repo_url,
        "branch": args.branch,
        "provider": detected["provider"],
        "clone_ok": commands[0]["returncode"] == 0,
        "install_ok": commands[1]["returncode"] == 0,
        "version_ok": commands[2]["returncode"] == 0,
        "github_status_ok": commands[3]["returncode"] == 0 and "Connected" in str(commands[3]["stdout"]),
        "github_repos_ok": commands[4]["returncode"] == 0 and "Repository" in str(commands[4]["stdout"]),
        "setup_ok": commands[5]["returncode"] == 0 and bool(config_summary.get("exists")),
        "setup_provider_ok": config_summary.get("provider") == detected["provider"],
        "setup_fallbacks_disabled": config_summary.get("allow_fallbacks") == "false",
        "setup_stale_provider_state_cleared": not any(
            [
                config_summary.get("has_dashscope_key"),
                config_summary.get("has_openai_key"),
                config_summary.get("has_nvidia_key"),
            ]
        ) if detected["provider"] == "ollama" else True,
        "doctor_ok": commands[6]["returncode"] == 0,
        "workspace_switch_ok": commands[7]["returncode"] == 0,
        "workspace_list_ok": commands[8]["returncode"] == 0 and "Recent Workspaces" in str(commands[8]["stdout"]),
        "github_clone_ok": commands[9]["returncode"] == 0 and (managed_clone_root / "viki-code").exists(),
        "home_shell_ok": commands[10]["returncode"] == 0 and "Prompt-First Console" in home_shell_output and "Primary Actions" in home_shell_output,
        "live_bugfix_ok": live_bugfix["returncode"] == 0 and "return a * b" in calculator_text and bugfix_pytest["returncode"] == 0,
        "sessions_list_ok": bool(bugfix_session) and any("sessions list" in str(item["command"]) and item["returncode"] == 0 for item in commands),
        "resume_ok": bool(bugfix_session) and any("sessions continue" in str(item["command"]) and item["returncode"] == 0 for item in commands),
        "rendered_diff_ok": bool(bugfix_session) and any(" --rendered" in str(item["command"]) and item["returncode"] == 0 for item in commands),
        "live_refactor_ok": live_refactor["returncode"] == 0 and "def normalize_account" in auth_text and "normalize_account" in service_text and refactor_pytest["returncode"] == 0,
        "live_bugfix_error": bugfix_error,
        "live_refactor_error": refactor_error,
        "live_provider_blocked": bool(bugfix_error or refactor_error),
        "config_home_removed": not config_home.exists(),
        "config_summary": config_summary,
    }
    summary["secret_matches"] = secret_match_count(output, env, list(detected["forwarded_keys"]))

    (output / "commands.json").write_text(json.dumps(commands, indent=2) + "\n", encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
