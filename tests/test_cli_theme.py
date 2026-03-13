from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from viki.cli import app
from viki.ui.cli_theme import create_terminal_ui


runner = CliRunner()


def test_terminal_ui_plain_mode_renders_without_panel_glyphs():
    terminal = create_terminal_ui(plain_requested=True, record=True, force_terminal=False, width=100)

    terminal.banner("4.1.4")
    terminal.header(
        "Execution",
        repo_root=Path("/tmp/repo"),
        branch="main",
        provider="dashscope",
        models="code:qwen",
        session_id="session-1",
        autonomy_mode="standard",
        approval_mode="auto",
        validation_state="pending",
    )

    output = terminal.console.export_text()
    assert "VIKI Code 4.1.4" in output
    assert f"Repo: {Path('/tmp/repo')}" in output
    assert "╭" not in output


def test_terminal_ui_styled_mode_renders_banner_header_and_diff():
    terminal = create_terminal_ui(plain_requested=False, theme_name="premium", force_terminal=True, record=True, width=100)

    terminal.banner("4.1.4")
    terminal.header(
        "Execution",
        repo_root=Path("/tmp/repo"),
        branch="main",
        provider="dashscope",
        models="code:qwen",
        session_id="session-1",
        autonomy_mode="standard",
        approval_mode="auto",
        validation_state="green",
    )
    terminal.render_diff_preview(
        [
            {
                "path": "app/calculator.py",
                "patch": "--- a/app/calculator.py\n+++ b/app/calculator.py\n@@ -1 +1 @@\n-return a + b\n+return a * b\n",
                "added": 1,
                "removed": 1,
            }
        ]
    )

    output = terminal.console.export_text()
    assert "VIKI Code" in output
    assert "Diff Preview" in output
    assert "app/calculator.py  +1 / -1" in output


def test_terminal_ui_auto_plain_in_ci(monkeypatch):
    monkeypatch.setenv("CI", "true")
    terminal = create_terminal_ui(record=True)
    assert terminal.plain is True


def test_cli_plain_flag_keeps_up_dry_run_readable(tmp_path: Path):
    result = runner.invoke(app, ["--plain", "up", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Workspace Runtime" in result.output
    assert "Dry run complete" in result.output
    assert "╭" not in result.output


def test_cli_force_rich_can_render_styled_output_in_captured_runs(tmp_path: Path):
    result = runner.invoke(app, ["--force-rich", "--theme", "premium", "up", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "VIKI Code" in result.output
    assert "\x1b[" in result.output or "╭" in result.output
