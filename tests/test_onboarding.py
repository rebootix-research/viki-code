from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from viki.cli import app


runner = CliRunner()


def test_setup_wizard_persists_provider_defaults_to_user_config(tmp_path: Path):
    config_home = tmp_path / "config-home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = runner.invoke(
        app,
        ["setup", str(workspace)],
        env={
            "VIKI_CONFIG_HOME": str(config_home),
            "DASHSCOPE_API_KEY": "redacted",
            "DASHSCOPE_API_BASE": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        },
        input="1\n1\ny\n\n1\n1\n1\nn\nn\n",
    )

    assert result.exit_code == 0, result.output
    config_path = config_home / "config.env"
    content = config_path.read_text(encoding="utf-8")
    assert "VIKI_PROVIDER=dashscope" in content
    assert "VIKI_CODING_MODEL=openai/qwen3-coder-next" in content
    assert "TELEGRAM_ENABLED=false" in content
    assert "WHATSAPP_ENABLED=false" in content
    assert "Setup Summary" in result.output


def test_setup_wizard_can_configure_telegram_and_skip_whatsapp(tmp_path: Path):
    config_home = tmp_path / "config-home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = runner.invoke(
        app,
        ["setup", str(workspace)],
        env={"VIKI_CONFIG_HOME": str(config_home), "OPENAI_API_KEY": "redacted"},
        input="2\n1\ny\n1\n1\n1\ny\nsecret-telegram-token\n123,456\nwebhook-secret\nn\n",
    )

    assert result.exit_code == 0, result.output
    content = (config_home / "config.env").read_text(encoding="utf-8")
    assert "VIKI_PROVIDER=openai" in content
    assert "TELEGRAM_ENABLED=true" in content
    assert "TELEGRAM_BOT_TOKEN=secret-telegram-token" in content
    assert "WHATSAPP_ENABLED=false" in content


def test_setup_wizard_supports_nvidia_kimi_profile(tmp_path: Path):
    config_home = tmp_path / "config-home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = runner.invoke(
        app,
        ["setup", str(workspace)],
        env={
            "VIKI_CONFIG_HOME": str(config_home),
            "NVIDIA_API_KEY": "redacted",
            "NVIDIA_API_BASE": "https://integrate.api.nvidia.com/v1",
        },
        input="6\n1\ny\n\n1\n1\n1\nn\nn\n",
    )

    assert result.exit_code == 0, result.output
    content = (config_home / "config.env").read_text(encoding="utf-8")
    assert "VIKI_PROVIDER=nvidia" in content
    assert "NVIDIA_API_KEY=redacted" in content
    assert "OPENAI_COMPAT_MODEL=openai/moonshotai/kimi-k2-5" in content


def test_default_entry_runs_guided_setup_and_initializes_workspace(tmp_path: Path, monkeypatch):
    config_home = tmp_path / "config-home"
    workspace = tmp_path / "repo"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    result = runner.invoke(
        app,
        [],
        env={
            "VIKI_CONFIG_HOME": str(config_home),
            "DASHSCOPE_API_KEY": "redacted",
            "DASHSCOPE_API_BASE": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        },
        input="1\n1\ny\n\n1\n1\n1\nn\nn\n\n",
    )

    assert result.exit_code == 0, result.output
    assert (workspace / ".viki-workspace").exists()
    assert "Prompt-First Console" in result.output
    assert "No task entered" in result.output


def test_default_entry_uses_existing_setup_and_skips_wizard(tmp_path: Path, monkeypatch):
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
    monkeypatch.chdir(workspace)

    result = runner.invoke(
        app,
        [],
        env={"VIKI_CONFIG_HOME": str(config_home)},
        input="\n",
    )

    assert result.exit_code == 0, result.output
    assert "guided you through provider" not in result.output.lower()
    assert "Prompt-First Console" in result.output
