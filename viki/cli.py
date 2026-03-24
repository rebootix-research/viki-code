from __future__ import annotations

import asyncio
import getpass
import json
import os
import shutil
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Any, Iterable, Optional

warnings.filterwarnings(
    "ignore",
    message=r".*urllib3 .* doesn't match a supported version.*",
)

import typer
import uvicorn
from click.exceptions import Abort as ClickAbort
from rich.table import Table

from . import __version__
from .api.server import create_app
from .config import refresh_settings, settings, user_config_path, write_user_config
from .core.hive import HiveMind
from .core.repo_index import RepoIndex
from .evals.suite import BenchmarkSuite
from .evals.scripted_provider import ScriptedEvalProvider
from .github_connect import GitHubRepo, clone_github_repo, detect_github_status, list_github_repos, managed_workspace_root
from .product_state import active_workspace_path, remember_workspace, recent_workspace_paths, set_active_workspace
from .ide.vscode import VSCodeIntegrator
from .infrastructure.database import DatabaseManager
from .infrastructure.observability import setup_logging, start_metrics_server
from .infrastructure.security import ContainerRuntimeProbe
from .integrations.telegram import TelegramBotClient
from .integrations.whatsapp import TwilioWhatsAppClient
from .ollama_support import DEFAULT_OLLAMA_BASE_URL, get_ollama_runtime_status
from .onboarding import (
    build_provider_env,
    get_model_profile,
    get_provider_preset,
    iter_provider_presets,
    messaging_reset_values,
    onboarding_state,
    provider_reset_values,
)
from .platforms import PlatformSupport
from .providers.litellm_provider import LiteLLMProvider
from .skills.factory import AutoSkillFactory
from .skills.package import SkillPackageManager
from .skills.registry import SkillRegistry
from .ui.cli_theme import PALETTES, create_terminal_ui

app = typer.Typer(help="VIKI Code - production-oriented swarm coding system", invoke_without_command=True, no_args_is_help=False)
skills_app = typer.Typer(help="Manage VIKI skills")
approvals_app = typer.Typer(help="Review approval queue")
ide_app = typer.Typer(help="IDE integration commands")
evals_app = typer.Typer(help="Benchmark and eval suite")
integrations_app = typer.Typer(help="Messaging integrations")
github_app = typer.Typer(help="GitHub connection and repo commands")
workspaces_app = typer.Typer(help="Workspace selection and switching")
sessions_app = typer.Typer(help="Session history and resume")
app.add_typer(skills_app, name="skills")
app.add_typer(approvals_app, name="approvals")
app.add_typer(ide_app, name="ide")
app.add_typer(evals_app, name="evals")
app.add_typer(integrations_app, name="integrations")
app.add_typer(github_app, name="github")
app.add_typer(workspaces_app, name="workspaces")
app.add_typer(sessions_app, name="sessions")
ui = create_terminal_ui()
console = ui.console


def _configure_terminal_ui(plain_requested: bool, theme_name: str, force_rich: bool = False) -> None:
    global ui, console
    normalized = theme_name.lower().strip()
    if normalized not in PALETTES:
        raise typer.BadParameter(f"Unknown theme '{theme_name}'. Choose from: {', '.join(sorted(PALETTES))}")
    ui = create_terminal_ui(
        plain_requested=plain_requested,
        theme_name=normalized,
        force_terminal=True if force_rich and not plain_requested else None,
    )
    console = ui.console


@app.callback()
def _main_callback(
    ctx: typer.Context,
    plain: bool = typer.Option(False, "--plain", help="Render plain terminal output without color or panels."),
    theme: str = typer.Option(settings.viki_theme or "premium", "--theme", help="CLI theme to use. Supported: premium, contrast."),
    force_rich: bool = typer.Option(False, "--force-rich", help="Force themed terminal rendering even when output is captured."),
):
    _configure_terminal_ui(plain, theme, force_rich=force_rich)
    if ctx.invoked_subcommand is None:
        _launch_default_entry(_default_entry_root(Path(".")))
        raise typer.Exit()


def _workspace_root(path: Path) -> Path:
    resolved = path.resolve()
    if _looks_like_repo_or_workspace(resolved):
        remember_workspace(resolved)
    return resolved


def _looks_like_repo_or_workspace(path: Path) -> bool:
    return any(
        [
            (path / ".git").exists(),
            (path / settings.workspace_dir).exists(),
            (path / "pyproject.toml").exists(),
            (path / "package.json").exists(),
            (path / "go.mod").exists(),
            (path / "Cargo.toml").exists(),
        ]
    )


def _default_entry_root(path: Path) -> Path:
    resolved = path.resolve()
    if _looks_like_repo_or_workspace(resolved):
        remember_workspace(resolved)
        return resolved
    active = active_workspace_path()
    if active:
        return active.resolve()
    return resolved


def _git_branch(root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except Exception:
        return "detached"
    branch = (completed.stdout or "").strip()
    return branch or "detached"


def _provider_summary(provider: Optional[LiteLLMProvider] = None) -> str:
    current = provider or LiteLLMProvider()
    if not current._available:
        return "unavailable"
    diagnostics = current.diagnostics()
    selected = diagnostics.get("selected_provider") or "unconfigured"
    fallbacks = [item for item in diagnostics.get("fallback_chain", []) if item != selected]
    if not fallbacks:
        return selected
    return f"{selected} -> {', '.join(fallbacks[:2])}"


def _model_summary(provider: Optional[LiteLLMProvider] = None) -> str:
    current = provider or LiteLLMProvider()
    slots = current.model_slots() if current._available else {
        "reasoning": settings.reasoning_model,
        "coding": settings.coding_model,
        "fast": settings.quick_model,
    }
    return " | ".join(
        [
            f"reason:{slots.get('reasoning', '-')}",
            f"code:{slots.get('coding', '-')}",
            f"fast:{slots.get('fast', '-')}",
        ]
    )


def _provider_diagnostics(provider: Optional[LiteLLMProvider] = None) -> dict[str, Any]:
    current = provider or LiteLLMProvider()
    return current.diagnostics() if current._available else {
        "litellm_available": False,
        "preferred_provider": None,
        "selected_provider": None,
        "fallback_chain": [],
        "configured_backends": [],
        "model_slots": {
            "reasoning": settings.reasoning_model,
            "coding": settings.coding_model,
            "fast": settings.quick_model,
        },
        "warnings": ["LiteLLM is unavailable in this environment."],
        "hints": ["Install the project dependencies before running live tasks."],
        "matrix": [],
    }


def _render_provider_overview(provider: Optional[LiteLLMProvider] = None) -> None:
    diagnostics = _provider_diagnostics(provider)
    table = Table(title="Provider Routing")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("LiteLLM", "OK" if diagnostics["litellm_available"] else "Missing")
    table.add_row("Preferred provider", diagnostics.get("preferred_provider") or "auto")
    table.add_row("Selected provider", diagnostics.get("selected_provider") or "unconfigured")
    table.add_row("Fallback chain", ", ".join(diagnostics.get("fallback_chain", [])) or "none")
    table.add_row("Configured backends", ", ".join(diagnostics.get("configured_backends", [])) or "none")
    table.add_row("Reasoning model", diagnostics["model_slots"].get("reasoning", "-"))
    table.add_row("Coding model", diagnostics["model_slots"].get("coding", "-"))
    table.add_row("Fast model", diagnostics["model_slots"].get("fast", "-"))
    ui.render_table(table)

    if diagnostics.get("matrix"):
        ui.section("Provider Matrix")
        matrix = Table(expand=True)
        matrix.add_column("Backend")
        matrix.add_column("Status")
        matrix.add_column("Required env")
        matrix.add_column("Base")
        matrix.add_column("Code model")
        for row in diagnostics["matrix"]:
            status = row["status"]
            if row.get("selected"):
                status = "selected"
            elif row.get("preferred") and row["status"] == "missing":
                status = "preferred-missing"
            matrix.add_row(
                row["name"],
                status,
                ", ".join(row["required_envs"]),
                row["base"],
                row["models"]["coding"],
            )
        ui.render_table(matrix)

    for warning in diagnostics.get("warnings", []):
        ui.warning(warning)
    for hint in diagnostics.get("hints", []):
        ui.info(hint)


def _render_ollama_runtime_summary() -> None:
    status = get_ollama_runtime_status(allow_pull=False)
    table = Table(title="Ollama Runtime")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("CLI", "available" if status.cli_available else "missing")
    table.add_row("Runtime", "reachable" if status.reachable else "unreachable")
    table.add_row("Base URL", status.base_url)
    table.add_row("Detected model", status.selected_model or "none")
    table.add_row("Recommended model", status.recommended_model)
    table.add_row("Installed models", ", ".join(status.models[:6]) or "none")
    ui.render_table(table)
    if status.error:
        ui.warning(status.error)


def _home_github_summary() -> tuple[str, list[GitHubRepo]]:
    status = detect_github_status()
    repos = list_github_repos(limit=8) if status.authenticated else []
    if not status.cli_available:
        return status.error or "GitHub CLI unavailable", []
    if not status.authenticated:
        return status.error or "Not connected", []
    repo_note = f"{len(repos)} repos visible" if repos else "connected"
    return f"{status.account or 'github'} ({repo_note})", repos


async def _recent_sessions_for_root(root: Path, limit: int = 5) -> list[dict[str, Any]]:
    db = _db_for_root(root)
    await db.initialize()
    return await db.get_recent_sessions(limit)


def _workspace_candidates(current_root: Path) -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()
    for item in [current_root, *recent_workspace_paths()]:
        candidate = item.resolve()
        key = str(candidate)
        if key in seen or not candidate.exists():
            continue
        seen.add(key)
        candidates.append(candidate)
    managed_root = managed_workspace_root()
    for item in sorted(path for path in managed_root.iterdir() if path.is_dir()):
        candidate = item.resolve()
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


def _render_recent_workspaces(current_root: Path) -> None:
    candidates = _workspace_candidates(current_root)
    if not candidates:
        return
    table = Table(title="Recent Workspaces")
    table.add_column("#", width=4)
    table.add_column("Workspace")
    table.add_column("State")
    for index, path in enumerate(candidates[:6], start=1):
        label = "active" if path.resolve() == current_root.resolve() else "recent"
        table.add_row(str(index), str(path), label)
    ui.render_table(table)


def _render_recent_sessions_block(root: Path) -> None:
    try:
        sessions = asyncio.run(_recent_sessions_for_root(root, limit=5))
    except RuntimeError:
        sessions = []
    if not sessions:
        return
    table = Table(title="Recent Sessions")
    table.add_column("#", width=4)
    table.add_column("Session")
    table.add_column("Status")
    table.add_column("Request")
    for index, item in enumerate(sessions, start=1):
        table.add_row(
            str(index),
            item["id"],
            item.get("status", "?"),
            (item.get("user_request") or "")[:60],
        )
    ui.render_table(table)


def _render_home_screen(root: Path, provider: LiteLLMProvider) -> None:
    _render_cli_header("Home", root=root, provider=provider, autonomy_mode=settings.default_run_mode, validation_state="ready")
    ui.section("Prompt-First Console")
    github_summary, repos = _home_github_summary()
    state_table = Table(title="Connected Product State")
    state_table.add_column("Area")
    state_table.add_column("Status")
    state_table.add_row("Workspace", str(root))
    state_table.add_row("Provider", _provider_summary(provider))
    state_table.add_row("GitHub", github_summary)
    state_table.add_row("Sessions", "available" if (root / settings.workspace_dir / "viki.db").exists() else "no history yet")
    ui.render_table(state_table)
    actions_table = Table(title="Primary Actions")
    actions_table.add_column("Action")
    actions_table.add_column("How")
    actions_table.add_row("Start task", "Type a task directly at the viki> prompt")
    actions_table.add_row("Open repo", "/workspace")
    actions_table.add_row("Connect GitHub", "/github")
    actions_table.add_row("Setup provider", "/setup")
    actions_table.add_row("Resume session", "/resume")
    actions_table.add_row("View approvals", "/approvals")
    actions_table.add_row("View diffs", "/diffs")
    ui.render_table(actions_table)
    if repos:
        repo_table = Table(title="GitHub Repos")
        repo_table.add_column("#", width=4)
        repo_table.add_column("Repository")
        repo_table.add_column("Visibility")
        for index, repo in enumerate(repos[:5], start=1):
            repo_table.add_row(str(index), repo.name_with_owner, "private" if repo.is_private else "public")
        ui.render_table(repo_table)
    _render_recent_workspaces(root)
    _render_recent_sessions_block(root)
    ui.render_hint_strip(
        [
            "Type a task naturally to start work",
            "Natural requests like 'fix this bug', 'rename this helper everywhere', or 'summarize this repo' work here",
            "Use /workspace to switch repos or reopen a recent workspace",
            "Use /github to browse and clone from the connected GitHub account",
            "Use /resume to continue a recent session",
            "Use /setup to revisit providers or messaging integrations",
        ],
        title="Prompt-first actions",
    )


def _manual_workspace_path() -> Path | None:
    raw = _prompt_text("Workspace path", allow_empty=True, default="")
    if not raw:
        return None
    candidate = Path(raw).expanduser().resolve()
    if not candidate.exists():
        ui.error(f"Workspace path does not exist: {candidate}")
        return None
    remember_workspace(candidate)
    return candidate


def _interactive_github_clone() -> Path | None:
    status = detect_github_status()
    if not status.cli_available:
        ui.warning(status.error or "GitHub CLI is unavailable.")
        return None
    if not status.authenticated:
        ui.warning(status.error or "GitHub CLI is not connected.")
        return None
    repos = list_github_repos(limit=10)
    if not repos:
        ui.warning("No GitHub repos were returned for the current account.")
        return None
    selection = _prompt_choice(
        "Choose a GitHub repo to clone",
        [(f"{repo.name_with_owner} - {repo.description or repo.url}", repo.name_with_owner) for repo in repos],
        default_index=1,
    )
    repo = repos[selection]
    target = clone_github_repo(repo.name_with_owner)
    remember_workspace(target)
    ui.success(f"Cloned {repo.name_with_owner} into {target}")
    return target


def _interactive_workspace_switch(current_root: Path) -> Path:
    candidates = _workspace_candidates(current_root)
    options = [(f"{path} - {'active' if path.resolve() == current_root.resolve() else 'recent'}", str(path)) for path in candidates]
    options.append(("Clone a repo from GitHub", "__github__"))
    options.append(("Enter a workspace path manually", "__manual__"))
    selection = _prompt_choice("Choose a workspace", options, default_index=1)
    chosen = options[selection][1]
    if chosen == "__github__":
        return _interactive_github_clone() or current_root
    if chosen == "__manual__":
        return _manual_workspace_path() or current_root
    target = Path(chosen).resolve()
    remember_workspace(target)
    ui.success(f"Active workspace set to {target}")
    return target


def _interactive_resume_flow(root: Path) -> None:
    sessions = asyncio.run(_recent_sessions_for_root(root, limit=8))
    if not sessions:
        ui.info("No recent sessions were found for this workspace yet.")
        return
    options = [
        (f"{item['id']} - {item.get('status', '?')} - {(item.get('user_request') or '')[:56]}", item["id"])
        for item in sessions
    ]
    selected = _prompt_choice("Choose a session to resume", options, default_index=1)
    session = sessions[selected]
    ui.info(f"Selected session {session['id']}")
    follow_up = _prompt_text("Follow-up request (leave empty to inspect only)", default="", allow_empty=True)
    if not follow_up:
        ui.info(f"Use `viki diff {session['id']} --path {root}` to inspect the last diff, or `viki status --session-id {session['id']}` for raw details.")
        return
    combined_prompt = (
        f"Continue from VIKI session {session['id']}.\n"
        f"Original request: {session.get('user_request') or 'unknown'}\n"
        f"Follow-up request: {follow_up}"
    )
    _run_live_session(combined_prompt, root=root, mode=settings.default_run_mode, detach=False, background_child=False)


def _interactive_diff_review(root: Path) -> None:
    sessions = asyncio.run(_recent_sessions_for_root(root, limit=8))
    if not sessions:
        ui.info("No recent sessions were found for this workspace yet.")
        return
    options = [
        (f"{item['id']} - {item.get('status', '?')} - {(item.get('user_request') or '')[:56]}", item["id"])
        for item in sessions
    ]
    selected = _prompt_choice("Choose a session to review", options, default_index=1)
    diff(options[selected][1], path=root, rendered=True)


def _render_cli_header(
    title: str,
    *,
    root: Path,
    provider: Optional[LiteLLMProvider] = None,
    session_id: Optional[str] = None,
    autonomy_mode: Optional[str] = None,
    validation_state: str = "pending",
) -> None:
    ui.banner(__version__)
    ui.header(
        title,
        repo_root=root,
        branch=_git_branch(root),
        provider=_provider_summary(provider),
        models=_model_summary(provider),
        session_id=session_id,
        autonomy_mode=autonomy_mode,
        approval_mode=settings.approval_mode,
        validation_state=validation_state,
    )


def _prompt_choice(title: str, options: list[tuple[str, str]], *, default_index: int = 1) -> int:
    ui.render_choice_menu(title, [(str(index + 1), label) for index, (label, _) in enumerate(options)])
    response = typer.prompt("Select an option", default=str(default_index)).strip()
    try:
        selected = int(response)
    except ValueError as exc:
        raise typer.BadParameter("Please enter a valid number.") from exc
    if selected < 1 or selected > len(options):
        raise typer.BadParameter("That choice is out of range.")
    return selected - 1


def _safe_secret_prompt(label: str) -> str:
    if os.name == "nt" and sys.stdin and sys.stdin.isatty():
        ui.info(f"{label}: using a PowerShell-safe secure prompt.")
        try:
            return getpass.getpass(f"{label}: ").strip()
        except (EOFError, KeyboardInterrupt):
            raise
        except Exception:
            ui.warning("Secure hidden input was not available in this terminal. VIKI will accept one visible line and will not echo it back in summaries.")
            return typer.prompt(label, hide_input=False).strip()
    return typer.prompt(label, hide_input=True).strip()


def _prompt_text(label: str, *, default: str | None = None, secret: bool = False, allow_empty: bool = False) -> str:
    if secret:
        value = _safe_secret_prompt(label)
    else:
        value = typer.prompt(label, default=default or "", show_default=bool(default)).strip()
    if value:
        return value.strip()
    if default is not None and not secret:
        return default
    if allow_empty:
        return ""
    raise typer.BadParameter(f"{label} is required.")


def _drain_console_input() -> None:
    try:
        if not sys.stdin or not sys.stdin.isatty():
            return
        if os.name == "nt":
            import msvcrt

            while msvcrt.kbhit():  # pragma: no branch - depends on user typing speed
                msvcrt.getwch()
            return
        import termios

        termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
    except Exception:
        return


def _existing_secret_for_preset(preset: ProviderPreset) -> str:
    candidates: list[str] = []
    if preset.secret_env:
        candidates.append(preset.secret_env)
    if preset.slug == "nvidia":
        candidates.extend(["OPENAI_API_KEY"])
    for env_name in candidates:
        field_name = env_name.lower()
        value = str(os.getenv(env_name, "") or getattr(settings, field_name, None) or "").strip()
        if value:
            return value
    return ""


def _existing_base_for_preset(preset: ProviderPreset) -> str:
    candidates: list[str] = []
    if preset.base_env:
        candidates.append(preset.base_env)
    if preset.slug == "nvidia":
        candidates.extend(["OPENAI_API_BASE"])
    for env_name in candidates:
        field_name = env_name.lower()
        value = str(os.getenv(env_name, "") or getattr(settings, field_name, None) or "").strip()
        if value:
            return value
    return str(preset.base_default or "")


def _choose_ollama_model_interactively(preset: ProviderPreset, profile: Any) -> tuple[Any, dict[str, str]]:
    status = get_ollama_runtime_status(allow_pull=False)
    updates: dict[str, str] = {}
    if status.cli_available and status.reachable and status.selected_model:
        return profile, updates

    if status.cli_available and status.reachable:
        ui.warning(f"Ollama is reachable, but no coding-capable local model is installed yet. Recommended model: {status.recommended_model}.")
        if typer.confirm(f"Pull {status.recommended_model} now?", default=True):
            pulling = get_ollama_runtime_status(allow_pull=True, preferred_model=status.recommended_model)
            if pulling.selected_model:
                updated_profile = get_model_profile(preset)
                updated_profile = type(updated_profile)(
                    slug=updated_profile.slug,
                    label=f"Local model: {pulling.selected_model}",
                    summary=updated_profile.summary,
                    reasoning=f"ollama/{pulling.selected_model}",
                    coding=f"ollama/{pulling.selected_model}",
                    fast=f"ollama/{pulling.selected_model}",
                )
                return updated_profile, updates
            ui.warning(pulling.error or "Ollama model pull did not complete.")
    elif status.cli_available and not status.reachable:
        ui.warning(status.error or "Ollama is installed, but the local runtime is not reachable.")
    else:
        ui.warning("Ollama CLI is not installed, so the local preset cannot validate the runtime here.")

    manual_model = _prompt_text("Ollama model name", default=status.recommended_model or DEFAULT_OLLAMA_PULL_MODEL)
    manual_base = _prompt_text("Ollama base URL", default=_existing_base_for_preset(preset) or DEFAULT_OLLAMA_BASE_URL)
    updates["OLLAMA_BASE_URL"] = manual_base
    updated_profile = type(profile)(
        slug=profile.slug,
        label=f"Local model: {manual_model}",
        summary=profile.summary,
        reasoning=f"ollama/{manual_model}",
        coding=f"ollama/{manual_model}",
        fast=f"ollama/{manual_model}",
    )
    return updated_profile, updates


def _setup_provider_configuration() -> tuple[dict[str, str | None], dict[str, str]]:
    presets = list(iter_provider_presets())
    index = _prompt_choice(
        "Choose your default AI provider",
        [(f"{preset.label} - {preset.description}", preset.slug) for preset in presets],
        default_index=1,
    )
    preset = presets[index]
    ui.info(f"{preset.label}: {preset.description}")
    if preset.notes:
        ui.info(preset.notes)

    profile_index = _prompt_choice(
        f"Choose a {preset.label} model profile",
        [(f"{profile.label} - {profile.summary}", profile.slug) for profile in preset.model_profiles],
        default_index=1,
    )
    profile = preset.model_profiles[profile_index]
    cleanup = provider_reset_values()

    secret_value: str | None = None
    if preset.secret_env:
        env_secret = _existing_secret_for_preset(preset)
        if env_secret and typer.confirm(f"Use the existing {preset.secret_env} from this shell?", default=True):
            secret_value = env_secret
        else:
            secret_value = _prompt_text(f"{preset.label} API key", secret=True)

    base_value: str | None = None
    if preset.base_env:
        current_base = _existing_base_for_preset(preset)
        base_value = _prompt_text(f"{preset.label} base URL", default=str(current_base) if current_base else None, allow_empty=False)

    if preset.slug == "ollama":
        profile, ollama_updates = _choose_ollama_model_interactively(preset, profile)
        cleanup.update(ollama_updates)
        base_value = cleanup.get("OLLAMA_BASE_URL") or base_value or _existing_base_for_preset(preset) or DEFAULT_OLLAMA_BASE_URL

    azure_api_version: str | None = None
    if preset.slug == "azure-openai":
        azure_api_version = _prompt_text("Azure API version", default=settings.azure_api_version or "2024-02-01-preview")

    config = build_provider_env(
        preset,
        profile,
        secret_value=secret_value,
        base_value=base_value,
        azure_api_version=azure_api_version,
    )
    cleanup.update(config)
    summary = {
        "Provider": preset.label,
        "Model profile": profile.label,
        "Reasoning": profile.reasoning,
        "Coding": profile.coding,
        "Fast": profile.fast,
    }
    if preset.slug == "ollama":
        summary["Ollama runtime"] = profile.coding.removeprefix("ollama/")
    return cleanup, summary


def _setup_integrations() -> tuple[dict[str, str | None], list[tuple[str, str]]]:
    updates: dict[str, str | None] = messaging_reset_values(enabled_channels=())
    optional: list[tuple[str, str]] = []
    enabled_channels: list[str] = []

    ui.section("Optional Messaging Integrations")
    ui.info("Telegram and WhatsApp are optional. You can skip them now and add them later with `viki setup --repair`.")

    if typer.confirm("Configure Telegram bot access now?", default=False):
        token = _prompt_text("Telegram bot token", secret=True)
        chat_ids = _prompt_text("Allowed Telegram chat IDs (comma-separated, optional)", default="", allow_empty=True)
        secret = _prompt_text("Telegram webhook secret (optional)", default="", allow_empty=True)
        updates.update(
            {
                "TELEGRAM_ENABLED": "true",
                "TELEGRAM_BOT_TOKEN": token,
                "TELEGRAM_ALLOWED_CHAT_IDS": chat_ids,
                "TELEGRAM_WEBHOOK_SECRET": secret,
            }
        )
        optional.append(("Telegram", "configured"))
        enabled_channels.append("telegram")
    else:
        optional.append(("Telegram", "skipped"))

    if typer.confirm("Configure WhatsApp via Twilio now?", default=False):
        updates.update(
            {
                "WHATSAPP_ENABLED": "true",
                "WHATSAPP_ACCOUNT_SID": _prompt_text("Twilio account SID"),
                "WHATSAPP_AUTH_TOKEN": _prompt_text("Twilio auth token", secret=True),
                "WHATSAPP_FROM_NUMBER": _prompt_text("WhatsApp from number", default="whatsapp:+0000000000"),
                "WHATSAPP_ALLOWED_SENDERS": _prompt_text("Allowed senders (comma-separated, optional)", default="", allow_empty=True),
                "WHATSAPP_WEBHOOK_URL": _prompt_text("Webhook URL (optional)", default="", allow_empty=True),
            }
        )
        optional.append(("WhatsApp", "configured"))
        enabled_channels.append("whatsapp")
    else:
        optional.append(("WhatsApp", "skipped"))
    if enabled_channels:
        updates = {**messaging_reset_values(enabled_channels=enabled_channels), **updates}
    return updates, optional


def _setup_preferences() -> tuple[dict[str, str], list[tuple[str, str]]]:
    theme_index = _prompt_choice(
        "Choose the default terminal theme",
        [
            ("Premium - dark-tech, polished interactive terminal UI", "premium"),
            ("Contrast - stronger contrast for some terminals", "contrast"),
        ],
        default_index=1,
    )
    theme_value = ["premium", "contrast"][theme_index]

    approval_index = _prompt_choice(
        "Choose the default approval mode",
        [
            ("Auto - only high-risk actions pause for approval", "auto"),
            ("Strict - ask for approval more aggressively", "strict"),
        ],
        default_index=1 if settings.approval_mode != "strict" else 2,
    )
    approval_value = ["auto", "strict"][approval_index]

    mode_index = _prompt_choice(
        "Choose the default session style",
        [
            ("Standard - balanced prompt-first workflow", "standard"),
            ("Careful - label sessions as more review-oriented", "careful"),
        ],
        default_index=1 if settings.default_run_mode != "careful" else 2,
    )
    mode_value = ["standard", "careful"][mode_index]

    updates = {
        "VIKI_THEME": theme_value,
        "APPROVAL_MODE": approval_value,
        "VIKI_DEFAULT_RUN_MODE": mode_value,
    }
    summary = [
        ("Theme", theme_value),
        ("Approvals", approval_value),
        ("Session style", mode_value),
    ]
    return updates, summary


def _run_setup_wizard(root: Path, *, title: str = "Setup Wizard", continue_to_prompt: bool = False) -> dict[str, Any]:
    remember_workspace(root)
    _render_cli_header(title, root=root, provider=LiteLLMProvider(), autonomy_mode="setup", validation_state="guided")
    ui.render_hint_strip(
        [
            "Choose one provider preset",
            "Save user-level config outside the repo",
            "Optionally configure Telegram or WhatsApp",
            "Start using VIKI immediately afterward",
        ],
        title="What this wizard will do",
    )
    provider_updates, provider_summary = _setup_provider_configuration()
    preference_updates, preference_summary = _setup_preferences()
    integration_updates, integration_summary = _setup_integrations()

    config_path = write_user_config({**provider_updates, **preference_updates, **integration_updates})
    refresh_settings()
    provider = LiteLLMProvider()
    configured = list(provider_summary.items()) + preference_summary
    optional = integration_summary + [("Workspace", "ready" if (root / settings.workspace_dir).exists() else "will initialize on first run")]
    ui.render_setup_summary(configured=configured, optional=optional, config_path=config_path)
    if settings.viki_provider == "ollama":
        _render_ollama_runtime_summary()
    if provider.validate_config():
        ui.success("Provider routing is ready.")
    else:
        ui.warning("Setup was saved, but the provider still looks incomplete. Re-run `viki setup --repair` if needed.")
    if continue_to_prompt:
        ui.render_hint_strip(
            [
                "Setup is complete. VIKI will return to the home shell next.",
                "The prompt buffer will be cleared before task entry.",
                "Type a task naturally once the viki> prompt appears.",
            ]
        )
    else:
        ui.render_hint_strip(
            [
                "Run `viki` for the prompt-first experience",
                "Run `viki doctor .` to review routing and runtime checks",
                "Run `viki providers` to inspect the active provider and model slots",
            ]
        )
    return {
        "config_path": str(config_path),
        "provider_ready": provider.validate_config(),
        "continue_to_prompt": continue_to_prompt,
        "provider": settings.viki_provider,
    }


def _ensure_workspace_ready(root: Path) -> None:
    remember_workspace(root)
    if (root / settings.workspace_dir).exists():
        return
    ui.warning("No VIKI workspace was found here, so VIKI is initializing this directory now.")
    _ensure_initialized(root)
    ui.success(f"Workspace initialized at {root / settings.workspace_dir}")


def _interactive_setup_repair(root: Path) -> LiteLLMProvider:
    ui.warning("Provider setup is incomplete. Launching the guided setup flow.")
    try:
        _run_setup_wizard(root, title="Repair Setup")
    except (EOFError, KeyboardInterrupt, ClickAbort):
        ui.error("Setup was cancelled before a provider was configured.")
        raise typer.Exit(1)
    provider = LiteLLMProvider()
    if not provider.validate_config():
        ui.error("Provider setup is still incomplete. Run `viki setup` to repair it.")
        _render_provider_overview(provider)
        raise typer.Exit(1)
    return provider


def _run_live_session(
    prompt: str,
    *,
    root: Path,
    mode: str,
    detach: bool = False,
    background_child: bool = False,
) -> None:
    remember_workspace(root)
    _ensure_workspace_ready(root)

    if detach and not background_child:
        cmd = [sys.executable, "-m", "viki.cli", "run", prompt, "--mode", mode, "--path", str(root), "--background-child"]
        proc = subprocess.Popen(cmd, cwd=str(root))
        _render_cli_header("Detached Run", root=root, autonomy_mode=mode, validation_state="queued")
        ui.success(f"Detached VIKI run started with PID {proc.pid}")
        return

    setup_logging(settings.log_level, settings.structured_logging)
    if settings.metrics_enabled:
        start_metrics_server(settings.metrics_port)
    provider = LiteLLMProvider()
    if not provider.validate_config():
        provider = _interactive_setup_repair(root)

    _render_cli_header("Live Session", root=root, provider=provider, autonomy_mode=mode, validation_state="pending")

    async def main():
        hive = HiveMind(provider, str(root))
        await hive.initialize()
        try:
            _render_cli_header(
                "Execution",
                root=root,
                provider=provider,
                session_id=hive.session_id,
                autonomy_mode=mode,
                validation_state="running",
            )
            result = await hive.process_request(prompt, mode=mode)
        finally:
            await hive.shutdown()
        _render_cli_header(
            "Completed Session",
            root=root,
            provider=provider,
            session_id=result["session_id"],
            autonomy_mode=mode,
            validation_state="green" if result["status"] == "completed" else result["status"],
        )
        ui.render_run_summary(result)
        if result["changed_files"]:
            ui.section("Changed Files")
            for path_item in result["changed_files"]:
                console.print(f"- {path_item}")
        if result["created_skills"]:
            ui.section("Created Skills")
            for item in result["created_skills"]:
                console.print(f"- {item['name']}: {item['path']}")
        ui.render_task_activity(result.get("task_results", []))
        ui.render_diff_preview(result.get("diff_preview", []), limit=3)
        ui.render_approvals(result.get("pending_approvals", []))
        failing = [entry for entry in result["commands"] if entry.get("returncode") not in (0, None)]
        if failing:
            ui.render_command_failures(failing)
        else:
            ui.success("Validation completed without non-zero command results.")
        return result

    try:
        asyncio.run(main())
    except Exception as exc:
        ui.error(f"VIKI run failed: {exc}")
        raise typer.Exit(1)


def _shell_action_from_prompt(prompt: str) -> str | None:
    lowered = prompt.strip().lower()
    if not lowered:
        return None
    if lowered in {"/quit", "/exit", "/help", "/workspace", "/github", "/resume", "/approvals", "/diffs", "/diff", "/setup", "/status"}:
        return lowered
    if any(token in lowered for token in ["continue the last task", "continue last task", "continue the last session", "continue last session", "resume session", "resume the last task"]):
        return "/resume"
    if any(token in lowered for token in ["show the last diff", "show last diff", "review last diff", "open the last diff", "show recent diffs"]):
        return "/diffs"
    if any(token in lowered for token in ["connect github", "open github", "browse github repos", "clone from github"]):
        return "/github"
    if any(token in lowered for token in ["switch workspace", "switch repo", "open repo", "choose workspace", "choose repo", "change workspace"]):
        return "/workspace"
    if any(token in lowered for token in ["set this up", "setup provider", "configure provider", "run setup", "open setup"]):
        return "/setup"
    if any(token in lowered for token in ["show status", "session status", "recent sessions", "what is active right now"]):
        return "/status"
    return None


def _launch_default_entry(root: Path) -> None:
    root = _default_entry_root(root)
    remember_workspace(root)

    while True:
        state = onboarding_state(root)
        provider = LiteLLMProvider()
        _render_home_screen(root, provider)

        if not state["config_exists"] or not state["provider_ready"]:
            ui.warning("Setup is incomplete, so VIKI will guide you through provider and messaging setup first.")
            try:
                _run_setup_wizard(root, continue_to_prompt=True)
            except (EOFError, KeyboardInterrupt, ClickAbort):
                ui.info("Run `viki setup` in an interactive terminal to complete onboarding.")
                return
            _drain_console_input()
            continue
        if not provider.validate_config():
            provider = _interactive_setup_repair(root)
            _drain_console_input()
            continue

        _ensure_workspace_ready(root)
        ui.render_hint_strip(
            [
                "Type a task naturally to start coding",
                "Examples: 'fix this bug', 'continue the last task', 'show the last diff', 'rename this helper everywhere'",
                "Use /workspace to switch repos or /github to clone from GitHub",
                "Use /resume to continue a prior session, /approvals to review gates, or /diffs to inspect changes",
            ],
            title="Enter a task or command",
        )

        try:
            prompt = typer.prompt("viki>", default="", show_default=False).strip()
        except (EOFError, KeyboardInterrupt, ClickAbort):
            ui.info("VIKI is configured. Run `viki` again in an interactive terminal or use `viki run \"...\"`.")
            return

        if not prompt:
            ui.info("No task entered. Use `viki` again for the home screen or `viki run \"...\"` for a direct task.")
            return

        command = _shell_action_from_prompt(prompt) or prompt.lower()
        if command in {"/quit", "/exit"}:
            ui.info("VIKI closed.")
            return
        if command == "/help":
            ui.render_hint_strip(
                [
                    "/workspace - switch the active workspace",
                    "/github - browse and clone from GitHub",
                    "/resume - continue a recent session",
                    "/approvals - review pending approval items",
                    "/diffs - inspect recent session diffs",
                    "/setup - revisit provider and messaging setup",
                    "/status - review recent sessions",
                    "Any other input starts a task in the active workspace",
                ],
                title="Home commands",
            )
            continue
        if command == "/workspace":
            root = _interactive_workspace_switch(root)
            continue
        if command == "/github":
            root = _interactive_github_clone() or root
            continue
        if command == "/resume":
            _interactive_resume_flow(root)
            continue
        if command == "/approvals":
            approvals_list(path=root)
            continue
        if command in {"/diffs", "/diff"}:
            _interactive_diff_review(root)
            continue
        if command == "/setup":
            _run_setup_wizard(root, title="Setup Wizard", continue_to_prompt=True)
            _drain_console_input()
            continue
        if command == "/status":
            status(path=root)
            continue
        _run_live_session(prompt, root=root, mode=settings.default_run_mode, detach=False, background_child=False)
        return


def _db_for_root(root: Path) -> DatabaseManager:
    return DatabaseManager(str(root / settings.workspace_dir / "viki.db"))


def _ensure_initialized(root: Path, force_env: bool = False) -> Path:
    workspace = settings.ensure_workspace(root)
    env_path = root / ".env"
    if force_env or not env_path.exists():
        env_path.write_text(_env_template(root / settings.workspace_dir / "viki.db"), encoding="utf-8")
    return workspace


def _env_template(workspace_db: Path) -> str:
    return f"""# VIKI routing
VIKI_PROVIDER=
VIKI_PROVIDER_ALLOW_FALLBACKS=false
VIKI_THEME={settings.viki_theme}
VIKI_DEFAULT_RUN_MODE={settings.default_run_mode}
VIKI_REASONING_MODEL=
VIKI_CODING_MODEL=
VIKI_FAST_MODEL=

# Primary providers
DASHSCOPE_API_KEY=
DASHSCOPE_API_BASE={settings.dashscope_api_base}
OPENROUTER_API_KEY=
OPENROUTER_API_BASE=https://openrouter.ai/api/v1
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
NVIDIA_API_KEY=
NVIDIA_API_BASE=https://integrate.api.nvidia.com/v1
GOOGLE_API_KEY=
DEEPSEEK_API_KEY=
GROQ_API_KEY=
MISTRAL_API_KEY=
TOGETHERAI_API_KEY=
FIREWORKS_API_KEY=
XAI_API_KEY=
CEREBRAS_API_KEY=
SAMBANOVA_API_KEY=
AZURE_API_KEY=
AZURE_API_BASE=
AZURE_API_VERSION=
OPENAI_API_BASE=
OPENAI_COMPAT_MODEL=
OLLAMA_BASE_URL={DEFAULT_OLLAMA_BASE_URL}
OLLAMA_MODEL={settings.local_model.removeprefix("ollama/")}

# Runtime
SANDBOX_ENABLED=true
MAX_COST_PER_TASK_USD=10
LOG_LEVEL=INFO
APPROVAL_MODE=auto
API_HOST={settings.api_host}
API_PORT={settings.api_port}
DATABASE_URL=sqlite:///{workspace_db}

# Telegram
TELEGRAM_ENABLED=false
TELEGRAM_BOT_TOKEN=
TELEGRAM_WEBHOOK_SECRET=
TELEGRAM_ALLOWED_CHAT_IDS=

# WhatsApp via Twilio
WHATSAPP_ENABLED=false
WHATSAPP_ACCOUNT_SID=
WHATSAPP_AUTH_TOKEN=
WHATSAPP_FROM_NUMBER=whatsapp:+0000000000
WHATSAPP_ALLOWED_SENDERS=
WHATSAPP_VALIDATE_SIGNATURE=true
WHATSAPP_WEBHOOK_URL=
"""


@app.command()
def setup(
    path: Path = typer.Argument(Path("."), help="Workspace root"),
    repair: bool = typer.Option(False, "--repair", help="Re-run the guided setup even if VIKI is already configured."),
):
    root = _workspace_root(path)
    state = onboarding_state(root)
    provider = LiteLLMProvider()
    if state["config_exists"] and state["provider_ready"] and provider.validate_config() and not repair:
        _render_cli_header("Setup", root=root, provider=provider, autonomy_mode="setup", validation_state="configured")
        ui.success("VIKI already has user-level provider configuration.")
        ui.render_setup_summary(
            configured=[
                ("Provider", str(state["provider_value"])),
                ("Theme", str(state["theme"])),
                ("Approvals", str(state["approval_mode"])),
                ("Session style", str(state["run_mode"])),
            ],
            optional=[
                ("Telegram", "configured" if state["telegram_enabled"] else "optional"),
                ("WhatsApp", "configured" if state["whatsapp_enabled"] else "optional"),
            ],
            config_path=user_config_path(),
        )
        ui.info("Use `viki setup --repair` to change providers, messaging, or defaults.")
        return
    _run_setup_wizard(root)


@app.command()
def init(path: Path = typer.Argument(Path('.'), help="Workspace root"), force: bool = typer.Option(False, "--force", "-f")):
    root = _workspace_root(path)
    _render_cli_header("Workspace Setup", root=root, autonomy_mode="bootstrap", validation_state="ready")
    workspace = root / settings.workspace_dir
    if workspace.exists() and not force:
        ui.warning("Workspace already initialized. Use --force to regenerate the template.")
        raise typer.Exit(1)
    workspace = _ensure_initialized(root, force_env=force)
    ui.success(f"Initialized VIKI workspace at {workspace}")
    ui.info("Run `viki` for the guided first-run experience or `viki doctor .` for diagnostics.")


@app.command()
def up(
    path: Path = typer.Argument(Path('.'), help="Workspace root"),
    host: str = typer.Option(settings.api_host, "--host"),
    port: int = typer.Option(settings.api_port, "--port"),
    force_env: bool = typer.Option(False, "--force-env", help="Rewrite .env template before starting"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Prepare workspace without starting the API server"),
):
    root = _workspace_root(path)
    _render_cli_header("Workspace Runtime", root=root, autonomy_mode="up", validation_state="ready")
    workspace = _ensure_initialized(root, force_env=force_env)
    PlatformSupport.write_local_launchers(root, Path(sys.executable).resolve())
    ui.success(f"VIKI workspace ready at {workspace}")
    if dry_run:
        ui.info("Dry run complete. Start with `viki` for the prompt-first experience or `viki up .` for the local API runtime.")
        return
    ui.info(f"Starting VIKI API on http://{host}:{port}")
    app_instance = create_app(root)
    uvicorn.run(app_instance, host=host, port=port)


@app.command()
def doctor(path: Path = typer.Argument(Path('.'), help="Workspace root")):
    root = _workspace_root(path)
    setup_logging(settings.log_level, settings.structured_logging)
    provider = LiteLLMProvider()
    _render_cli_header("Doctor", root=root, provider=provider, autonomy_mode="diagnostic", validation_state="checks")
    state = onboarding_state(root)
    profile = PlatformSupport.current()
    table = Table(title="VIKI Doctor")
    table.add_column("Check")
    table.add_column("Status")

    workspace = root / settings.workspace_dir
    table.add_row("Workspace", "OK" if workspace.exists() else "Missing")
    table.add_row("User config", str(user_config_path()))
    table.add_row("Setup state", "Ready" if state["provider_ready"] else "Needs provider setup")
    table.add_row("Platform", profile.os_name)
    table.add_row("Shell", profile.shell)
    diagnostics = _provider_diagnostics(provider)
    table.add_row("LiteLLM", "OK" if provider._available else "Missing")
    table.add_row("Providers", ", ".join(diagnostics.get("configured_backends", [])) or "No API backend configured")
    table.add_row("Selected provider", diagnostics.get("selected_provider") or "auto")

    try:
        import docker
        client = docker.from_env()
        client.ping()
        docker_status = "OK"
    except Exception:
        docker_status = "Unavailable"
    table.add_row("Docker", docker_status)

    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        git_status = "OK"
    except Exception:
        git_status = "Unavailable"
    table.add_row("Git", git_status)
    runtimes = ContainerRuntimeProbe().probe_all()
    best_runtime = ContainerRuntimeProbe().best_available(runtimes)
    table.add_row("Isolation runtime", f"{best_runtime.name}:{best_runtime.detail}" if best_runtime else "None available")

    registry = SkillRegistry(root)
    table.add_row("Skills", str(len(registry.list_skills())))
    table.add_row("Approvals", settings.approval_mode)
    table.add_row("Theme", settings.viki_theme)
    table.add_row("Default session", settings.default_run_mode)
    table.add_row("API", f"{settings.api_host}:{settings.api_port}")
    table.add_row("Launcher", profile.launcher_hint)
    ui.render_table(table)
    _render_provider_overview(provider)
    _render_ollama_runtime_summary()


@app.command("providers")
def providers_status():
    provider = LiteLLMProvider()
    _render_cli_header("Providers", root=Path("."), provider=provider, autonomy_mode="provider-routing", validation_state="diagnostic")
    ui.info(f"User config path: {user_config_path()}")
    _render_provider_overview(provider)
    _render_ollama_runtime_summary()


@app.command("platforms")
def platform_info():
    profile = PlatformSupport.current()
    ui.banner(__version__)
    table = Table(title="VIKI Platform Support")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("OS", profile.os_name)
    table.add_row("Family", profile.family)
    table.add_row("Shell", profile.shell)
    table.add_row("Python", profile.python_executable)
    table.add_row("Venv Python", profile.venv_python)
    table.add_row("Launcher", profile.launcher_name)
    table.add_row("Shortcut", profile.launcher_hint)
    ui.render_table(table)


@app.command()
def version():
    console.print(__version__)


@app.command()
def home(path: Path = typer.Argument(Path("."), help="Workspace root or any directory inside the product shell")):
    _launch_default_entry(_default_entry_root(path))


@app.command()
def run(
    prompt: str = typer.Argument(..., help="Task for VIKI"),
    mode: str = typer.Option(settings.default_run_mode, "--mode", "-m"),
    path: Path = typer.Option(Path('.'), "--path", help="Workspace root"),
    detach: bool = typer.Option(False, "--detach", "-d"),
    background_child: bool = typer.Option(False, "--background-child", hidden=True),
):
    root = _workspace_root(path)
    _run_live_session(prompt, root=root, mode=mode, detach=detach, background_child=background_child)


@github_app.command("status")
def github_status():
    status = detect_github_status()
    table = Table(title="GitHub Connection")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("CLI", "available" if status.cli_available else "missing")
    table.add_row("Connected", "yes" if status.authenticated else "no")
    table.add_row("Account", status.account or "-")
    table.add_row("Protocol", status.protocol or "-")
    table.add_row("Scopes", status.scopes or "-")
    if status.error:
        table.add_row("Message", status.error)
    ui.render_table(table)
    if status.cli_available and not status.authenticated:
        ui.info("Run `gh auth login` once, then use `viki github repos` or `/github` inside VIKI.")


@github_app.command("repos")
def github_repos(owner: Optional[str] = typer.Option(None, "--owner", help="GitHub owner or org"), limit: int = typer.Option(12, "--limit")):
    repos = list_github_repos(owner=owner, limit=limit)
    if not repos:
        status = detect_github_status()
        if not status.authenticated:
            ui.warning("GitHub is not connected yet. Run `gh auth login`, then retry `viki github repos`.")
        else:
            ui.warning("No GitHub repos are available for the connected account or owner.")
        raise typer.Exit(1)
    table = Table(title="GitHub Repositories")
    table.add_column("Repository")
    table.add_column("Visibility")
    table.add_column("Default branch")
    table.add_column("Description")
    for repo in repos:
        table.add_row(
            repo.name_with_owner,
            "private" if repo.is_private else "public",
            repo.default_branch or "-",
            repo.description or "-",
        )
    ui.render_table(table)


@github_app.command("clone")
def github_clone(
    repo: str = typer.Argument(..., help="GitHub repo in owner/name form"),
    branch: Optional[str] = typer.Option(None, "--branch", help="Optional branch"),
    destination: Optional[Path] = typer.Option(None, "--destination", help="Target workspace root"),
):
    target = clone_github_repo(repo, target_root=destination, branch=branch)
    remember_workspace(target)
    ui.success(f"Workspace ready at {target}")


@workspaces_app.command("list")
def workspaces_list():
    state = recent_workspace_paths()
    if not state:
        ui.info("No recent workspaces yet. Run `viki` in a repo or use `viki github clone`.")
        raise typer.Exit()
    active = active_workspace_path()
    table = Table(title="Recent Workspaces")
    table.add_column("Workspace")
    table.add_column("State")
    for item in state:
        table.add_row(str(item), "active" if active and item.resolve() == active.resolve() else "recent")
    ui.render_table(table)


@workspaces_app.command("use")
def workspaces_use(path: Path = typer.Argument(..., help="Workspace to make active")):
    root = path.resolve()
    if not root.exists():
        ui.error(f"Workspace does not exist: {root}")
        raise typer.Exit(1)
    set_active_workspace(root)
    ui.success(f"Active workspace set to {root}")


@sessions_app.command("list")
def sessions_list(path: Path = typer.Argument(Path("."), help="Workspace root"), limit: int = typer.Option(10, "--limit")):
    root = _workspace_root(path)

    async def main():
        sessions = await _recent_sessions_for_root(root, limit=limit)
        table = Table(title="Recent Sessions")
        table.add_column("Session")
        table.add_column("Status")
        table.add_column("Request")
        for item in sessions:
            table.add_row(item["id"], item.get("status", "?"), (item.get("user_request") or "")[:72])
        ui.render_table(table)

    asyncio.run(main())


@sessions_app.command("continue")
def sessions_continue(
    session_id: str = typer.Argument(..., help="Session id to continue from"),
    prompt: Optional[str] = typer.Option(None, "--prompt", help="Follow-up request"),
    path: Path = typer.Option(Path("."), "--path", help="Workspace root"),
):
    root = _workspace_root(path)
    db = _db_for_root(root)

    async def main() -> dict[str, Any] | None:
        await db.initialize()
        return await db.get_session(session_id)

    session = asyncio.run(main())
    if not session:
        ui.error(f"Session not found: {session_id}")
        raise typer.Exit(1)
    follow_up = prompt or _prompt_text("Follow-up request", allow_empty=True, default="")
    if not follow_up:
        ui.info(f"Selected session {session_id}. Use `viki diff {session_id} --path {root}` to inspect it.")
        raise typer.Exit()
    combined_prompt = (
        f"Continue from VIKI session {session_id}.\n"
        f"Original request: {session.get('user_request') or 'unknown'}\n"
        f"Follow-up request: {follow_up}"
    )
    _run_live_session(combined_prompt, root=root, mode=settings.default_run_mode, detach=False, background_child=False)


@app.command()
def repo(
    query: str = typer.Argument("repo overview", help="Repo search query"),
    path: Path = typer.Option(Path('.'), "--path", help="Workspace root"),
    limit: int = typer.Option(12, "--limit", help="Number of matches to show"),
):
    root = _workspace_root(path)
    index = RepoIndex(root)
    payload = index.context_pack(query, limit=limit)
    console.print_json(json.dumps(payload))


@app.command()
def symbols(
    query: str = typer.Argument("", help="Symbol search query"),
    path: Path = typer.Option(Path('.'), "--path", help="Workspace root"),
    file: list[str] = typer.Option([], "--file", help="Restrict to one or more repo paths"),
    limit: int = typer.Option(20, "--limit", help="Number of symbols to show"),
):
    root = _workspace_root(path)
    index = RepoIndex(root)
    payload = {"query": query, "items": index.symbols(query=query, paths=file, limit=limit)}
    console.print_json(json.dumps(payload))


@app.command()
def impact(
    changed_file: list[str] = typer.Option([], "--changed-file", help="Changed file path, repeat for multiple entries"),
    path: Path = typer.Option(Path('.'), "--path", help="Workspace root"),
    limit: int = typer.Option(20, "--limit", help="Neighbor/test limit"),
):
    root = _workspace_root(path)
    index = RepoIndex(root)
    payload = index.impact_report(changed_file, limit=limit)
    console.print_json(json.dumps(payload))


@app.command()
def diff(
    session_id: str = typer.Argument(..., help="Session id to inspect"),
    path: Path = typer.Option(Path('.'), "--path", help="Workspace root"),
    rendered: bool = typer.Option(False, "--rendered", help="Show a themed diff preview instead of raw JSON."),
):
    root = _workspace_root(path)
    db = _db_for_root(root)

    async def main():
        await db.initialize()
        session = await db.get_session(session_id)
        if not session:
            ui.error(f"Session not found: {session_id}")
            raise typer.Exit(1)
        payload = session.get("result_json")
        if isinstance(payload, str):
            payload = json.loads(payload) if payload else {}
        payload = payload or {}
        if rendered:
            _render_cli_header("Diff Review", root=root, session_id=session_id, autonomy_mode="review", validation_state="recorded")
            ui.render_diff_preview(payload.get("diff_preview", []), limit=12)
            patch_bundles = payload.get("patch_bundles", [])
            if patch_bundles:
                ui.section("Patch Bundles")
                for bundle in patch_bundles:
                    console.print(f"- {bundle}")
            return
        console.print_json(json.dumps({"diff_preview": payload.get("diff_preview", []), "patch_bundles": payload.get("patch_bundles", [])}))

    asyncio.run(main())


@app.command()
def status(path: Path = typer.Argument(Path('.'), help="Workspace root"), session_id: Optional[str] = typer.Option(None, "--session-id")):
    root = _workspace_root(path)
    db = _db_for_root(root)

    async def main():
        await db.initialize()
        if session_id:
            session = await db.get_session(session_id)
            console.print_json(json.dumps(session or {}))
            return
        _render_cli_header("Session Status", root=root, autonomy_mode="status", validation_state="history")
        sessions = await db.get_recent_sessions(10)
        table = Table(title="Recent VIKI sessions")
        table.add_column("Session")
        table.add_column("Status")
        table.add_column("Request")
        for item in sessions:
            table.add_row(item["id"], item.get("status", "?"), (item.get("user_request") or "")[:60])
        ui.render_table(table)

    asyncio.run(main())


@app.command()
def resume(path: Path = typer.Argument(Path('.'), help="Workspace root")):
    root = _workspace_root(path)
    provider = LiteLLMProvider()

    async def main():
        hive = HiveMind(provider, str(root))
        await hive.initialize()
        state = await hive.resume_last_session()
        console.print_json(json.dumps(state))

    asyncio.run(main())


@app.command()
def tui(path: Path = typer.Argument(Path('.'), help="Workspace root")):
    from .ui.dashboard import launch_dashboard

    root = _workspace_root(path)
    launch_dashboard(root / settings.workspace_dir / "viki.db")


@app.command()
def serve(path: Path = typer.Argument(Path('.'), help="Workspace root"), host: str = typer.Option(settings.api_host), port: int = typer.Option(settings.api_port)):
    root = _workspace_root(path)
    app_instance = create_app(root)
    uvicorn.run(app_instance, host=host, port=port)


@skills_app.command("list")
def skills_list(path: Path = typer.Argument(Path('.'), help="Workspace root")):
    registry = SkillRegistry(_workspace_root(path))
    table = Table(title="VIKI Skills")
    table.add_column("Name")
    table.add_column("Version")
    table.add_column("Permissions")
    table.add_column("Trust")
    table.add_column("Source")
    table.add_column("Description")
    for record in registry.list_skills():
        trust = "signed" if record.signed else record.integrity
        table.add_row(record.name, record.version, ", ".join(record.permissions or []), trust, record.source, record.description)
    console.print(table)


@skills_app.command("templates")
def skills_templates(path: Path = typer.Argument(Path('.'), help="Workspace root")):
    factory = AutoSkillFactory(_workspace_root(path), provider=None)
    table = Table(title="VIKI Skill Templates")
    table.add_column("Template")
    table.add_column("Use")
    for name in factory.available_templates():
        table.add_row(name, f"viki skills create \"...\" --template {name}")
    console.print(table)


@skills_app.command("init")
def skills_init(
    name: str = typer.Argument(..., help="Skill name"),
    description: str = typer.Option(..., "--description", help="Skill description"),
    template: str = typer.Option("workspace_reader", "--template", help="Skill template"),
    path: Path = typer.Argument(Path('.'), help="Workspace root"),
):
    factory = AutoSkillFactory(_workspace_root(path), provider=None)

    async def main():
        result = await factory.create_skill(description, preferred_name=name, template=template)
        console.print_json(json.dumps(result))

    asyncio.run(main())


@skills_app.command("create")
def skills_create(
    description: str = typer.Argument(...),
    name: Optional[str] = typer.Option(None, "--name"),
    template: Optional[str] = typer.Option(None, "--template", help="Use a local template instead of provider generation"),
    permission: list[str] = typer.Option([], "--permission", help="Explicit permission, repeat for multiple entries"),
    dependency: list[str] = typer.Option([], "--dependency", help="Pinned package requirement, repeat for multiple entries"),
    path: Path = typer.Argument(Path('.')),
):
    provider = LiteLLMProvider()
    factory = AutoSkillFactory(_workspace_root(path), provider=provider)

    async def main():
        result = await factory.create_skill(
            description,
            preferred_name=name,
            template=template,
            permissions=permission or None,
            dependencies=dependency or None,
        )
        console.print_json(json.dumps(result))

    asyncio.run(main())


@skills_app.command("pack")
def skills_pack(
    skill_path: Path = typer.Argument(..., help="Directory containing main.py and manifest.yaml"),
    output: Optional[Path] = typer.Option(None, "--output", help="Output archive path"),
    path: Path = typer.Argument(Path('.'), help="Workspace root"),
):
    manager = SkillPackageManager(_workspace_root(path))
    result = manager.pack(skill_path, output_path=output)
    console.print_json(json.dumps(result))


@skills_app.command("install")
def skills_install(
    archive: Path = typer.Argument(..., help="Local .vskill.zip archive"),
    path: Path = typer.Argument(Path('.'), help="Workspace root"),
):
    manager = SkillPackageManager(_workspace_root(path))
    result = manager.install(archive)
    console.print_json(json.dumps(result))


@skills_app.command("prepare-env")
def skills_prepare_env(
    name: str = typer.Argument(..., help="Skill name"),
    path: Path = typer.Argument(Path('.'), help="Workspace root"),
    upgrade: bool = typer.Option(False, "--upgrade", help="Recreate the skill environment before installing dependencies"),
):
    registry = SkillRegistry(_workspace_root(path))
    result = registry.prepare_environment(name, upgrade=upgrade)
    console.print_json(json.dumps(result))


@skills_app.command("invoke")
def skills_invoke(
    name: str = typer.Argument(..., help="Skill name"),
    payload: str = typer.Option("{}", "--payload", help="JSON payload passed to the skill"),
    permission: list[str] = typer.Option([], "--permission", help="Granted permission, repeat for multiple entries"),
    isolation: str = typer.Option("", "--isolation", help="Override isolation mode for this run"),
    path: Path = typer.Argument(Path('.'), help="Workspace root"),
):
    registry = SkillRegistry(_workspace_root(path))
    try:
        parsed_payload = json.loads(payload)
    except json.JSONDecodeError as exc:
        ui.error(f"Invalid payload JSON: {exc}")
        raise typer.Exit(1)
    context = {
        "workspace": str(_workspace_root(path)),
        "allowed_permissions": permission or ["workspace:read", "workspace:write", "command:run"],
        "isolation": isolation or None,
    }
    result = registry.invoke(name, parsed_payload, context)
    console.print_json(json.dumps(result))


@skills_app.command("validate")
def skills_validate(path: Path = typer.Argument(Path('.'), help="Workspace root")):
    registry = SkillRegistry(_workspace_root(path))
    invalid = []
    for record in registry.list_skills():
        try:
            if record.source != "builtin":
                registry.invoke(
                    record.name,
                    {"files": []} if "workspace:read" in (record.permissions or []) else {},
                    {
                        "workspace": str(_workspace_root(path)),
                        "allowed_permissions": record.permissions or ["workspace:read"],
                        "persist_changes": False,
                    },
                )
        except Exception as exc:
            invalid.append((record.name, str(exc)))
    if invalid:
        for name, error in invalid:
            ui.error(f"{name}: {error}")
        raise typer.Exit(1)
    ui.success("All skills loaded successfully")


@approvals_app.command("list")
def approvals_list(path: Path = typer.Argument(Path('.'), help="Workspace root"), status: str = typer.Option("pending", "--status")):
    root = _workspace_root(path)
    db = _db_for_root(root)

    async def main():
        await db.initialize()
        _render_cli_header("Approvals", root=root, autonomy_mode="approval-review", validation_state=status)
        rows = await db.list_approvals(status=status, limit=100)
        table = Table(title=f"Approvals ({status})")
        table.add_column("ID")
        table.add_column("Type")
        table.add_column("Risk")
        table.add_column("Subject")
        for row in rows:
            table.add_row(str(row["id"]), row.get("request_type", ""), str(row.get("risk_score", 0)), row.get("subject", ""))
        ui.render_table(table)

    asyncio.run(main())


@approvals_app.command("approve")
def approvals_approve(approval_id: int = typer.Argument(...), path: Path = typer.Argument(Path('.')), scope: str = typer.Option("once", "--scope")):
    root = _workspace_root(path)
    db = _db_for_root(root)

    async def main():
        await db.initialize()
        await db.resolve_approval(approval_id, status="approved", reviewer=f"cli-user:{scope}")
        _render_cli_header("Approval Granted", root=root, autonomy_mode="approval-review", validation_state="approved")
        ui.success(f"Approved #{approval_id} ({scope})")

    asyncio.run(main())


@approvals_app.command("reject")
def approvals_reject(approval_id: int = typer.Argument(...), path: Path = typer.Argument(Path('.'))):
    root = _workspace_root(path)
    db = _db_for_root(root)

    async def main():
        await db.initialize()
        await db.resolve_approval(approval_id, status="rejected", reviewer="cli-user")
        _render_cli_header("Approval Rejected", root=root, autonomy_mode="approval-review", validation_state="rejected")
        ui.warning(f"Rejected #{approval_id}")

    asyncio.run(main())


@ide_app.command("vscode")
def ide_vscode(path: Path = typer.Argument(Path('.'), help="Workspace root")):
    root = _workspace_root(path)
    written = VSCodeIntegrator(root).install()
    console.print_json(json.dumps(written))


@ide_app.command("vscode-extension")
def ide_vscode_extension(path: Path = typer.Argument(Path('.'), help="Workspace root")):
    root = _workspace_root(path)
    written = VSCodeIntegrator(root).install_extension_scaffold()
    console.print_json(json.dumps(written))


@evals_app.command("run")
def evals_run(
    path: Path = typer.Argument(Path('.'), help="Workspace root"),
    dataset: list[str] = typer.Option(["public"], "--dataset", help="Benchmark dataset to run; repeat for multiple sets"),
    cases_dir: Optional[Path] = typer.Option(None, "--cases-dir", help="Directory containing benchmark case manifests"),
    agent_name: str = typer.Option("VIKI Code", "--agent-name", help="Agent name recorded in the benchmark report"),
    offline_scripted: bool = typer.Option(False, "--offline-scripted", help="Run the benchmark suite with the deterministic offline provider"),
):
    root = _workspace_root(path)
    provider = ScriptedEvalProvider() if offline_scripted else LiteLLMProvider()
    if not offline_scripted and not provider.validate_config():
        ui.error("No provider configuration detected. Export provider env vars or configure .env before running benchmarks.")
        _render_provider_overview(provider)
        raise typer.Exit(1)

    async def main():
        cases = BenchmarkSuite.load_cases(root, datasets=dataset, cases_dir=cases_dir)
        suite = BenchmarkSuite(root, provider, cases=cases or None, agent_name=agent_name)
        report = await suite.run()
        report_path = BenchmarkSuite.save_report(root, report)
        console.print_json(json.dumps({"report": report, "path": str(report_path)}))

    asyncio.run(main())


@evals_app.command("compare")
def evals_compare(
    report: Path = typer.Argument(..., help="Primary benchmark report JSON"),
    baseline: list[str] = typer.Option([], "--baseline", help="Baseline in the form name=path/to/report.json"),
    path: Path = typer.Argument(Path('.'), help="Workspace root"),
):
    baselines = {}
    for item in baseline:
        if "=" not in item:
            ui.error(f"Invalid baseline: {item}")
            raise typer.Exit(1)
        name, report_path = item.split("=", 1)
        baselines[name] = json.loads(Path(report_path).read_text(encoding="utf-8"))
    subject = json.loads(report.read_text(encoding="utf-8"))
    comparison = BenchmarkSuite.compare_reports(subject, baselines)
    output = BenchmarkSuite.save_comparison(_workspace_root(path), comparison)
    console.print_json(json.dumps({"comparison": comparison, "path": str(output)}))


@evals_app.command("publish")
def evals_publish(
    report: Path = typer.Argument(..., help="Benchmark report JSON"),
    comparison: Optional[Path] = typer.Option(None, "--comparison", help="Optional comparison JSON"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", help="Directory where the board is published"),
    path: Path = typer.Argument(Path('.'), help="Workspace root"),
):
    subject = json.loads(report.read_text(encoding="utf-8"))
    comparison_payload = json.loads(comparison.read_text(encoding="utf-8")) if comparison else None
    output = BenchmarkSuite.publish_board(_workspace_root(path), subject, comparison=comparison_payload, output_dir=output_dir)
    console.print_json(json.dumps({"output": str(output)}))


@integrations_app.command("status")
def integrations_status():
    telegram = TelegramBotClient()
    whatsapp = TwilioWhatsAppClient()
    _render_cli_header("Integrations", root=Path("."), autonomy_mode="integration-status", validation_state="ready")
    table = Table(title="VIKI Integrations")
    table.add_column("Channel")
    table.add_column("Enabled")
    table.add_column("Policy")
    table.add_row("Telegram", "yes" if telegram.enabled else "no", "secret" if telegram.secret else "open")
    table.add_row("WhatsApp", "yes" if whatsapp.enabled else "no", "signed" if settings.whatsapp_validate_signature else "unsigned")
    ui.render_table(table)


def main():
    app()


if __name__ == "__main__":
    main()
