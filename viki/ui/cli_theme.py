from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, TextIO

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.theme import Theme as RichTheme


@dataclass(frozen=True)
class Palette:
    border: str
    accent: str
    accent_soft: str
    text: str
    muted: str
    success: str
    warning: str
    danger: str
    info: str
    diff_add: str
    diff_remove: str
    diff_meta: str


PALETTES: dict[str, Palette] = {
    "premium": Palette(
        border="#32506f",
        accent="#7ad7ff",
        accent_soft="#4f7ca1",
        text="#f3f7fb",
        muted="#97a8b8",
        success="#42d392",
        warning="#f5b754",
        danger="#ff6b6b",
        info="#7ad7ff",
        diff_add="#1f8f63",
        diff_remove="#b24c5c",
        diff_meta="#7c8ea3",
    ),
    "contrast": Palette(
        border="#5e6d7e",
        accent="#9be2ff",
        accent_soft="#6f879f",
        text="#f8fbff",
        muted="#b3c0cc",
        success="#54d998",
        warning="#ffc566",
        danger="#ff7d7d",
        info="#9be2ff",
        diff_add="#24a269",
        diff_remove="#c75d6a",
        diff_meta="#91a0b1",
    ),
}


def _build_theme(palette: Palette) -> RichTheme:
    return RichTheme(
        {
            "viki.border": palette.border,
            "viki.accent": f"bold {palette.accent}",
            "viki.accent_soft": palette.accent_soft,
            "viki.text": palette.text,
            "viki.muted": palette.muted,
            "viki.success": f"bold {palette.success}",
            "viki.warning": f"bold {palette.warning}",
            "viki.danger": f"bold {palette.danger}",
            "viki.info": palette.info,
            "viki.badge.label": f"bold {palette.muted}",
            "viki.badge.value": f"bold {palette.text}",
            "viki.table.header": f"bold {palette.accent}",
            "viki.diff.add": palette.diff_add,
            "viki.diff.remove": palette.diff_remove,
            "viki.diff.meta": palette.diff_meta,
        }
    )


def _rich_supported(*, plain_requested: bool, force_terminal: Optional[bool], stream: TextIO | None) -> bool:
    if plain_requested:
        return False
    if force_terminal is not None:
        return bool(force_terminal)
    if os.getenv("CI") or os.getenv("NO_COLOR") or os.getenv("TERM") == "dumb":
        return False
    candidate = stream or sys.stdout
    return bool(getattr(candidate, "isatty", lambda: False)())


def create_terminal_ui(
    *,
    plain_requested: bool = False,
    theme_name: str = "premium",
    force_terminal: Optional[bool] = None,
    record: bool = False,
    stream: TextIO | None = None,
    width: int | None = None,
    stderr: bool = False,
) -> "TerminalUI":
    palette = PALETTES.get(theme_name, PALETTES["premium"])
    rich_supported = _rich_supported(
        plain_requested=plain_requested,
        force_terminal=force_terminal,
        stream=stream,
    )
    console = Console(
        theme=_build_theme(palette) if rich_supported else None,
        color_system="truecolor" if rich_supported else None,
        no_color=not rich_supported,
        force_terminal=bool(force_terminal) if force_terminal is not None else False,
        highlight=rich_supported,
        soft_wrap=True,
        record=record,
        file=stream,
        width=width,
        stderr=stderr,
    )
    return TerminalUI(console=console, theme_name=theme_name if theme_name in PALETTES else "premium", plain=not rich_supported, palette=palette)


class TerminalUI:
    def __init__(self, *, console: Console, theme_name: str, plain: bool, palette: Palette):
        self.console = console
        self.theme_name = theme_name
        self.plain = plain
        self.palette = palette
        self._banner_printed = False

    def banner(self, version: str) -> None:
        if self._banner_printed:
            return
        self._banner_printed = True
        if self.plain:
            self.console.print(f"VIKI Code {version}")
            self.console.print("Governed coding infrastructure for real repositories.")
            self.console.print("")
            return
        title = Text("VIKI Code", style="viki.accent")
        title.append("  ")
        title.append(version, style="viki.muted")
        subtitle = Text("Governed coding infrastructure for approvals, rollback, live validation, and repo execution.", style="viki.text")
        footer = Text("Rebootix terminal runtime", style="viki.accent_soft")
        self.console.print(
            Panel(
                Group(title, subtitle, footer),
                border_style="viki.border",
                box=box.HEAVY,
                padding=(1, 2),
            )
        )

    def header(
        self,
        title: str,
        *,
        repo_root: Path | None = None,
        branch: str | None = None,
        provider: str | None = None,
        models: str | None = None,
        session_id: str | None = None,
        autonomy_mode: str | None = None,
        approval_mode: str | None = None,
        validation_state: str | None = None,
    ) -> None:
        entries = [
            ("Repo", str(repo_root) if repo_root else "-"),
            ("Branch", branch or "-"),
            ("Provider", provider or "-"),
            ("Models", models or "-"),
            ("Session", session_id or "-"),
            ("Mode", autonomy_mode or "-"),
            ("Approvals", approval_mode or "-"),
            ("Validation", validation_state or "-"),
        ]
        if self.plain:
            self.console.print(title)
            for label, value in entries:
                self.console.print(f"{label}: {value}")
            self.console.print("")
            return
        grid = Table.grid(expand=True, padding=(0, 1))
        grid.add_column(ratio=1)
        grid.add_column(ratio=1)
        for index in range(0, len(entries), 2):
            left = self._kv_text(*entries[index])
            right = self._kv_text(*entries[index + 1])
            grid.add_row(left, right)
        self.console.print(
            Panel(
                grid,
                title=f"[viki.accent]{title}[/viki.accent]",
                border_style="viki.border",
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )

    def section(self, title: str) -> None:
        if self.plain:
            self.console.print(f"\n## {title}")
            return
        self.console.print(Rule(Text(title, style="viki.accent"), style="viki.border"))

    def info(self, message: str) -> None:
        self._message(message, "INFO", "viki.info")

    def success(self, message: str) -> None:
        self._message(message, "OK", "viki.success")

    def warning(self, message: str) -> None:
        self._message(message, "WARN", "viki.warning")

    def error(self, message: str) -> None:
        self._message(message, "ERROR", "viki.danger")

    def render_table(self, table: Table, *, title: str | None = None) -> None:
        if self.plain:
            self.console.print(table)
            return
        table.box = box.SIMPLE_HEAVY
        table.header_style = "viki.table.header"
        table.border_style = self.palette.border
        table.row_styles = ["", "dim"]
        if title:
            self.console.print(Panel(table, title=f"[viki.accent]{title}[/viki.accent]", border_style="viki.border", box=box.ROUNDED))
            return
        self.console.print(table)

    def render_task_activity(self, task_results: Iterable[dict[str, Any]]) -> None:
        items = list(task_results)
        if not items:
            return
        self.section("Agent Activity")
        table = Table(expand=True)
        table.add_column("Task")
        table.add_column("Lane")
        table.add_column("Sync")
        table.add_column("Confidence")
        table.add_column("Validation")
        table.add_column("Files")
        for item in items:
            route = item.get("route", {})
            task = item.get("task", {})
            sync = (item.get("sync", {}) or {}).get("status", "-")
            validation = f"{item.get('validation_successes', 0)} ok / {item.get('evidence', {}).get('failure_count', 0)} fail"
            files = ", ".join((item.get("changed_files") or item.get("candidate_changed_files") or [])[:3]) or "-"
            table.add_row(
                str(task.get("title") or task.get("id") or "-"),
                str(route.get("lane", "-")),
                sync,
                f"{float(item.get('confidence', 0.0) or 0.0):.2f}",
                validation,
                files,
            )
        self.render_table(table)

    def render_approvals(self, approvals: Iterable[dict[str, Any]]) -> None:
        items = list(approvals)
        if not items:
            return
        self.section("Approvals")
        table = Table(expand=True)
        table.add_column("ID")
        table.add_column("Type")
        table.add_column("Risk")
        table.add_column("Subject")
        for item in items:
            table.add_row(
                str(item.get("id", "-")),
                str(item.get("request_type", "-")),
                str(item.get("risk_score", "-")),
                str(item.get("subject", "-")),
            )
        self.render_table(table)

    def render_command_failures(self, failures: Iterable[dict[str, Any]]) -> None:
        items = list(failures)
        if not items:
            return
        self.section("Validation Attention")
        for item in items:
            command = str(item.get("command", "-"))
            error = str(item.get("error") or item.get("output") or "").strip() or "Command returned a non-zero exit code."
            if self.plain:
                self.console.print(f"- {command}: {error}")
                continue
            self.console.print(
                Panel(
                    Text(error, style="viki.text"),
                    title=f"[viki.warning]{command}[/viki.warning]",
                    border_style="viki.warning",
                    box=box.ROUNDED,
                )
            )

    def render_diff_preview(self, previews: Iterable[dict[str, Any]], *, limit: int = 3) -> None:
        items = list(previews)[:limit]
        if not items:
            return
        self.section("Diff Preview")
        for item in items:
            title = f"{item.get('path', '-')}  +{item.get('added', 0)} / -{item.get('removed', 0)}"
            patch = str(item.get("patch", "")).rstrip()
            if self.plain:
                self.console.print(title)
                if patch:
                    self.console.print(patch)
                self.console.print("")
                continue
            self.console.print(
                Panel(
                    self._styled_diff(patch),
                    title=f"[viki.accent]{title}[/viki.accent]",
                    border_style="viki.border",
                    box=box.ROUNDED,
                    padding=(0, 1),
                )
            )

    def render_run_summary(self, result: dict[str, Any]) -> None:
        self.section("Execution Summary")
        rows = [
            ("Status", str(result.get("status", "-"))),
            ("Changed files", str(len(result.get("changed_files", [])))),
            ("Patch bundles", str(len(result.get("patch_bundles", [])))),
            ("Approvals", str(len(result.get("pending_approvals", [])))),
            ("Testing", str((result.get("testing") or {}).get("source", "model-driven"))),
            ("Security", str(((result.get("security") or {}).get("model_findings") or {}).get("source", "model-driven"))),
        ]
        if self.plain:
            for label, value in rows:
                self.console.print(f"{label}: {value}")
            return
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(ratio=1)
        table.add_column(ratio=1)
        for index in range(0, len(rows), 2):
            left = self._kv_text(*rows[index])
            right = self._kv_text(*rows[index + 1]) if index + 1 < len(rows) else Text("")
            table.add_row(left, right)
        self.console.print(Panel(table, border_style="viki.border", box=box.ROUNDED))

    def _kv_text(self, label: str, value: str) -> Text:
        text = Text()
        text.append(f"{label.upper()} ", style="viki.badge.label")
        text.append(value, style="viki.badge.value")
        return text

    def _message(self, message: str, prefix: str, style: str) -> None:
        if self.plain:
            self.console.print(f"[{prefix}] {message}")
            return
        self.console.print(Panel(Text(message, style="viki.text"), title=f"[{style}]{prefix}[/{style}]", border_style=style, box=box.ROUNDED))

    def _styled_diff(self, patch: str) -> Text:
        text = Text()
        for line in patch.splitlines():
            if line.startswith(("---", "+++", "@@")):
                style = "viki.diff.meta"
            elif line.startswith("+"):
                style = "viki.diff.add"
            elif line.startswith("-"):
                style = "viki.diff.remove"
            else:
                style = "viki.text"
            text.append(line + "\n", style=style)
        return text if text else Text("No diff available.", style="viki.muted")
