from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from viki.infrastructure.security import SecurityScanner

PROVIDER_ENV_PRIORITY = [
    ("dashscope", ["DASHSCOPE_API_KEY"], ["DASHSCOPE_API_KEY", "DASHSCOPE_API_BASE", "VIKI_PROVIDER", "VIKI_REASONING_MODEL", "VIKI_CODING_MODEL", "VIKI_FAST_MODEL"]),
    ("openrouter", ["OPENROUTER_API_KEY"], ["OPENROUTER_API_KEY", "OPENROUTER_API_BASE", "VIKI_PROVIDER", "VIKI_REASONING_MODEL", "VIKI_CODING_MODEL", "VIKI_FAST_MODEL"]),
    ("openai-compatible", ["OPENAI_API_KEY", "OPENAI_API_BASE"], ["OPENAI_API_KEY", "OPENAI_API_BASE", "OPENAI_COMPAT_MODEL", "VIKI_PROVIDER", "VIKI_REASONING_MODEL", "VIKI_CODING_MODEL", "VIKI_FAST_MODEL"]),
    ("openai", ["OPENAI_API_KEY"], ["OPENAI_API_KEY", "VIKI_PROVIDER", "VIKI_REASONING_MODEL", "VIKI_CODING_MODEL", "VIKI_FAST_MODEL"]),
    ("anthropic", ["ANTHROPIC_API_KEY"], ["ANTHROPIC_API_KEY", "VIKI_PROVIDER", "VIKI_REASONING_MODEL", "VIKI_CODING_MODEL", "VIKI_FAST_MODEL"]),
    ("google", ["GOOGLE_API_KEY"], ["GOOGLE_API_KEY", "VIKI_PROVIDER", "VIKI_REASONING_MODEL", "VIKI_CODING_MODEL", "VIKI_FAST_MODEL"]),
    ("ollama", ["OLLAMA_BASE_URL"], ["OLLAMA_BASE_URL", "OLLAMA_MODEL", "VIKI_PROVIDER", "VIKI_REASONING_MODEL", "VIKI_CODING_MODEL", "VIKI_FAST_MODEL"]),
]


def detect_live_provider(env: dict[str, str]) -> dict[str, object]:
    preferred = env.get("VIKI_PROVIDER", "").strip().lower()
    if preferred:
        for name, required, keys in PROVIDER_ENV_PRIORITY:
            if name == preferred and all(env.get(key) for key in required):
                return {"provider": name, "forwarded_keys": [key for key in keys if env.get(key)]}

    for name, required, keys in PROVIDER_ENV_PRIORITY:
        if required and all(env.get(key) for key in required):
            return {"provider": name, "forwarded_keys": [key for key in keys if env.get(key)]}

    if env.get("OPENAI_API_KEY") and env.get("OPENAI_API_BASE"):
        return {"provider": "openai-compatible", "forwarded_keys": ["OPENAI_API_KEY", "OPENAI_API_BASE"]}
    if env.get("OPENAI_API_KEY"):
        return {"provider": "openai", "forwarded_keys": ["OPENAI_API_KEY"]}
    return {"provider": None, "forwarded_keys": []}


def copy_fixture(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def run_command(command: list[str], cwd: Path, env: dict[str, str], timeout: int, security: SecurityScanner) -> dict[str, object]:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the public GitHub repo from a fresh PowerShell-style clone and install flow.")
    parser.add_argument("--repo-url", default="https://github.com/rebootix-research/viki-code.git")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--output", default="LIVE_RUN_RESULTS/github_clone_live", help="Directory for redacted validation artifacts")
    args = parser.parse_args()

    output = Path(args.output).resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    security = SecurityScanner()
    env = os.environ.copy()
    provider = detect_live_provider(env)
    if not provider["provider"]:
        raise RuntimeError("No live provider environment variables are available in the current session.")

    clone_dir = output / "viki-code"
    venv_dir = output / "venv"
    commands: list[dict[str, object]] = []

    commands.append(run_command(["git", "clone", "--depth", "1", "--branch", args.branch, args.repo_url, str(clone_dir)], output, env, 1200, security))
    commands.append(run_command([sys.executable, "-m", "venv", str(venv_dir)], output, env, 600, security))

    scripts_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    python_bin = scripts_dir / ("python.exe" if os.name == "nt" else "python")
    pip_bin = scripts_dir / ("pip.exe" if os.name == "nt" else "pip")
    viki_bin = scripts_dir / ("viki.exe" if os.name == "nt" else "viki")

    commands.append(run_command([str(python_bin), "-m", "pip", "install", "--upgrade", "pip"], output, env, 1200, security))
    commands.append(run_command([str(pip_bin), "install", ".", "pytest"], clone_dir, env, 2400, security))
    commands.append(run_command([str(viki_bin), "--force-rich", "--theme", "premium", "version"], clone_dir, env, 300, security))
    commands.append(run_command([str(viki_bin), "--force-rich", "--theme", "premium", "--help"], clone_dir, env, 300, security))
    commands.append(run_command([str(viki_bin), "--force-rich", "--theme", "premium", "providers"], clone_dir, env, 300, security))
    commands.append(run_command([str(viki_bin), "--plain", "doctor", str(clone_dir)], clone_dir, env, 300, security))

    bugfix_repo = output / "generic_bugfix_repo"
    refactor_repo = output / "generic_refactor_repo"
    copy_fixture(clone_dir / "benchmarks" / "public" / "generic_bugfix" / "fixture", bugfix_repo)
    copy_fixture(clone_dir / "benchmarks" / "public" / "generic_refactor" / "fixture", refactor_repo)

    commands.append(run_command([str(viki_bin), "--plain", "up", str(bugfix_repo), "--dry-run"], clone_dir, env, 300, security))
    bugfix_run = run_command(
        [
            str(viki_bin),
            "--force-rich",
            "--theme",
            "premium",
            "run",
            "Fix the broken calculation and make tests pass.",
            "--path",
            str(bugfix_repo),
        ],
        clone_dir,
        env,
        2400,
        security,
    )
    commands.append(bugfix_run)

    bugfix_session = parse_session_id(str(bugfix_run["stdout"]))
    if bugfix_session:
        commands.append(run_command([str(viki_bin), "--force-rich", "--theme", "premium", "diff", bugfix_session, "--path", str(bugfix_repo), "--rendered"], clone_dir, env, 300, security))

    bugfix_pytest = run_command([str(python_bin), "-m", "pytest", "--rootdir", ".", "tests/test_calculator.py", "-q"], bugfix_repo, env, 300, security)
    commands.append(bugfix_pytest)
    refactor_run = run_command(
        [
            str(viki_bin),
            "--plain",
            "run",
            "Refactor auth naming consistently and keep behavior green.",
            "--path",
            str(refactor_repo),
        ],
        clone_dir,
        env,
        2400,
        security,
    )
    commands.append(refactor_run)
    refactor_pytest = run_command([str(python_bin), "-m", "pytest", "--rootdir", ".", "tests/test_service.py", "-q"], refactor_repo, env, 300, security)
    commands.append(refactor_pytest)

    bugfix_content = (bugfix_repo / "app" / "calculator.py").read_text(encoding="utf-8", errors="ignore")
    refactor_auth = (refactor_repo / "packages" / "shared" / "auth.py").read_text(encoding="utf-8", errors="ignore")
    refactor_service = (refactor_repo / "apps" / "api" / "service.py").read_text(encoding="utf-8", errors="ignore")

    summary = {
        "repo_url": args.repo_url,
        "branch": args.branch,
        "provider": provider["provider"],
        "forwarded_env_keys": provider["forwarded_keys"],
        "clone_ok": commands[0]["returncode"] == 0,
        "install_ok": commands[3]["returncode"] == 0,
        "premium_help_ok": commands[5]["returncode"] == 0,
        "provider_diagnostics_ok": commands[6]["returncode"] == 0,
        "plain_doctor_ok": commands[7]["returncode"] == 0,
        "plain_dry_run_ok": commands[8]["returncode"] == 0,
        "live_bugfix_ok": bugfix_run["returncode"] == 0 and "return a * b" in bugfix_content and bugfix_pytest["returncode"] == 0,
        "live_refactor_ok": refactor_run["returncode"] == 0 and "def normalize_account" in refactor_auth and "normalize_account" in refactor_service and refactor_pytest["returncode"] == 0,
        "rendered_diff_ok": bool(bugfix_session) and any("--rendered" in " ".join(item["command"]) and item["returncode"] == 0 for item in commands),
        "premium_command_path_ok": bugfix_run["returncode"] == 0,
        "plain_command_path_ok": refactor_run["returncode"] == 0,
        "session_id": bugfix_session,
        "clone_dir": str(clone_dir),
    }

    (output / "commands.json").write_text(json.dumps(commands, indent=2) + "\n", encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
