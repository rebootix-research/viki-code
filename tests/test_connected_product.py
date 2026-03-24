from __future__ import annotations

import asyncio
from pathlib import Path

from typer.testing import CliRunner

from viki.cli import _shell_action_from_prompt, app
from viki.github_connect import GitHubRepo, GitHubStatus
from viki.infrastructure.database import DatabaseManager
from viki.product_state import active_workspace_path, load_product_state, remember_workspace, set_active_workspace


runner = CliRunner()


def test_product_state_tracks_active_and_recent_workspaces(tmp_path: Path, monkeypatch):
    config_home = tmp_path / "config-home"
    monkeypatch.setenv("VIKI_CONFIG_HOME", str(config_home))

    first = tmp_path / "repo-a"
    second = tmp_path / "repo-b"
    first.mkdir()
    second.mkdir()

    remember_workspace(first)
    remember_workspace(second)

    state = load_product_state()
    assert state.active_workspace == str(second.resolve())
    assert list(state.recent_workspaces[:2]) == [str(second.resolve()), str(first.resolve())]


def test_home_command_uses_active_workspace_when_current_dir_is_not_a_repo(tmp_path: Path, monkeypatch):
    config_home = tmp_path / "config-home"
    config_home.mkdir(parents=True)
    (config_home / "config.env").write_text(
        "\n".join(
            [
                "VIKI_PROVIDER=dashscope",
                "DASHSCOPE_API_KEY=redacted",
                "DASHSCOPE_API_BASE=https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                "VIKI_CODING_MODEL=openai/qwen3-coder-next",
                "",
            ]
        ),
        encoding="utf-8",
    )
    workspace = tmp_path / "repo"
    workspace.mkdir()
    blank = tmp_path / "blank"
    blank.mkdir()

    monkeypatch.setenv("VIKI_CONFIG_HOME", str(config_home))
    monkeypatch.chdir(blank)
    monkeypatch.setattr(
        "viki.cli.detect_github_status",
        lambda: GitHubStatus(True, True, "rebootix-research", "https", "repo", None),
    )
    monkeypatch.setattr(
        "viki.cli.list_github_repos",
        lambda owner=None, limit=20: [
            GitHubRepo(
                name_with_owner="rebootix-research/viki-code",
                url="https://github.com/rebootix-research/viki-code",
                is_private=False,
                default_branch="main",
                description="VIKI Code",
            )
        ],
    )

    set_active_workspace(workspace)
    result = runner.invoke(app, ["home"], env={"VIKI_CONFIG_HOME": str(config_home)}, input="\n")

    assert result.exit_code == 0, result.output
    assert "Prompt-First Console" in result.output
    assert "Primary Actions" in result.output
    assert str(workspace.resolve()) in result.output
    assert "rebootix-research/viki-code" in result.output


def test_workspaces_commands_list_and_set_active_workspace(tmp_path: Path, monkeypatch):
    config_home = tmp_path / "config-home"
    monkeypatch.setenv("VIKI_CONFIG_HOME", str(config_home))

    first = tmp_path / "repo-a"
    second = tmp_path / "repo-b"
    first.mkdir()
    second.mkdir()

    remember_workspace(first)
    remember_workspace(second)

    listed = runner.invoke(app, ["--plain", "workspaces", "list"], env={"VIKI_CONFIG_HOME": str(config_home)})
    assert listed.exit_code == 0, listed.output
    assert "repo-a" in listed.output
    assert "repo-b" in listed.output

    switched = runner.invoke(app, ["--plain", "workspaces", "use", str(first)], env={"VIKI_CONFIG_HOME": str(config_home)})
    assert switched.exit_code == 0, switched.output
    assert active_workspace_path() == first.resolve()


def test_github_commands_surface_connected_repositories(monkeypatch):
    monkeypatch.setattr(
        "viki.cli.detect_github_status",
        lambda: GitHubStatus(True, True, "rebootix-research", "https", "repo,workflow", None),
    )
    monkeypatch.setattr(
        "viki.cli.list_github_repos",
        lambda owner=None, limit=12: [
            GitHubRepo(
                name_with_owner="rebootix-research/viki-code",
                url="https://github.com/rebootix-research/viki-code",
                is_private=False,
                default_branch="main",
                description="Governed coding infrastructure",
            )
        ],
    )

    status_result = runner.invoke(app, ["--plain", "github", "status"])
    repos_result = runner.invoke(app, ["--plain", "github", "repos"])

    assert status_result.exit_code == 0, status_result.output
    assert "rebootix-research" in status_result.output
    assert repos_result.exit_code == 0, repos_result.output
    assert "GitHub Repositories" in repos_result.output
    assert "infrastructure" in repos_result.output


def test_sessions_commands_list_and_continue_without_follow_up(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()

    async def seed() -> None:
        db = DatabaseManager(str(root / ".viki-workspace" / "viki.db"))
        await db.initialize()
        await db.create_session("20260324-010101", "Fix the auth naming", "main", {"workspace": str(root)})

    asyncio.run(seed())

    listed = runner.invoke(app, ["--plain", "sessions", "list", str(root)])
    continued = runner.invoke(app, ["--plain", "sessions", "continue", "20260324-010101", "--path", str(root)], input="\n")

    assert listed.exit_code == 0, listed.output
    assert "20260324-010101" in listed.output
    assert continued.exit_code == 0, continued.output
    assert "Selected session 20260324-010101" in continued.output


def test_prompt_first_shell_maps_natural_language_to_product_actions():
    assert _shell_action_from_prompt("continue the last task") == "/resume"
    assert _shell_action_from_prompt("show the last diff") == "/diffs"
    assert _shell_action_from_prompt("connect github") == "/github"
    assert _shell_action_from_prompt("switch workspace") == "/workspace"
