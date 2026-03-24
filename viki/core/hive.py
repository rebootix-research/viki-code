from __future__ import annotations

import asyncio
import json
import re
import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .._log import structlog
from ..config import settings
from ..infrastructure.database import DatabaseManager
from ..infrastructure.observability import MetricsCollector
from ..infrastructure.resilience import GracefulShutdown, RateLimiter
from ..infrastructure.security import DockerSandbox, SecurityScanner
from ..skills.factory import AutoSkillFactory
from ..skills.registry import SkillRegistry
from .actions import WorkspaceExecutor
from .approvals import ApprovalManager, ApprovalRequest
from .context import ContextCompressor
from .memory import MemoryBank
from .merge import MergeResolver
from .repair import FailureClassifier
from .repo_index import RepoIndex
from .routing import TaskRoute, TaskRouter
from .swarm import SwarmConfig, SwarmPod, SwarmType
from .worktree import WorktreeManager

logger = structlog.get_logger()

PLANNING_SCHEMA = """
{
  "goal": "string",
  "summary": "string",
  "tasks": [
    {
      "id": "task-1",
      "title": "string",
      "objective": "string",
      "target_files": ["path/to/file"],
      "deliverables": ["what gets created"],
      "commands": [{"command": "pytest -q", "timeout": 120}],
      "skill_requests": [{"name": "skill_name", "description": "what the skill should do"}],
      "subtasks": [{"id": "task-1-1", "title": "string", "objective": "string"}]
    }
  ],
  "testing_commands": [{"command": "pytest -q", "timeout": 120}],
  "acceptance_criteria": ["criterion"]
}
""".strip()

CODING_SCHEMA = """
{
  "task_id": "task-1",
  "summary": "string",
  "file_operations": [
    {"mode": "write", "path": "relative/path.ext", "content": "full file content"},
    {"mode": "replace_block", "path": "relative/path.ext", "old": "exact old text", "new": "replacement text", "count": 1},
    {"mode": "ast_replace_function", "path": "relative/path.ext", "symbol": "function_name", "content": "def function(...): ..."},
    {"mode": "patch", "path": "relative/path.ext", "patch": "unified diff text"},
    {"mode": "append|mkdir|delete|json_merge", "path": "relative/path.ext"}
  ],
  "commands": [{"command": "pytest -q", "timeout": 120}],
  "skill_requests": [{"name": "skill_name", "description": "what the skill should do"}],
  "notes": ["important implementation notes"]
}
""".strip()

TESTING_SCHEMA = """
{
  "summary": "string",
  "commands": [{"command": "pytest -q", "timeout": 120}],
  "expected_outputs": ["string"]
}
""".strip()

SECURITY_SCHEMA = """
{
  "summary": "string",
  "issues": [{"severity": "low|medium|high", "path": "file", "issue": "description"}],
  "recommended_commands": [{"command": "python -m compileall .", "timeout": 120}]
}
""".strip()

REPAIR_SCHEMA = """
{
  "summary": "string",
  "root_cause": "string",
  "file_operations": [
    {"mode": "write", "path": "relative/path.ext", "content": "full file content"},
    {"mode": "replace_block", "path": "relative/path.ext", "old": "exact old text", "new": "replacement text", "count": 1},
    {"mode": "ast_replace_function", "path": "relative/path.ext", "symbol": "function_name", "content": "def function(...): ..."},
    {"mode": "patch", "path": "relative/path.ext", "patch": "unified diff text"}
  ],
  "commands": [{"command": "pytest -q", "timeout": 120}],
  "notes": ["string"]
}
""".strip()


class HiveMind:
    def __init__(self, provider: Any, workspace_path: str = "."):
        self.provider = provider
        self.workspace = Path(workspace_path).resolve()
        self.db = DatabaseManager()
        self.security = SecurityScanner()
        self.sandbox = DockerSandbox()
        self.executor = WorkspaceExecutor(self.workspace, security=self.security, sandbox=self.sandbox)
        self.metrics = MetricsCollector()
        self.rate_limiter = RateLimiter(settings.max_api_calls_per_minute)
        self.shutdown_manager = GracefulShutdown()
        self.registry = SkillRegistry(self.workspace)
        self.skill_factory = AutoSkillFactory(self.workspace, provider=provider)
        self.active_swarms: List[SwarmPod] = []
        self.session_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        self._checkpoint_task: asyncio.Task | None = None
        self.compressor = ContextCompressor(settings.context_budget_chars)
        self.merge_resolver = MergeResolver()
        self.approvals = ApprovalManager(self.db, self.security)
        self.memory = MemoryBank(self.db)
        self.worktrees = WorktreeManager(self.workspace, self.workspace / settings.runs_dir)
        self.repo_index = RepoIndex(self.workspace)
        self.router = TaskRouter()
        self.failure_classifier = FailureClassifier()
        self.shutdown_manager.add_cleanup_handler(self._cleanup)

    async def initialize(self):
        settings.ensure_workspace(self.workspace)
        self.db = DatabaseManager(str(self.workspace / settings.workspace_dir / "viki.db"))
        await self.db.initialize()
        self.approvals = ApprovalManager(self.db, self.security)
        self.memory = MemoryBank(self.db)
        self._checkpoint_task = asyncio.create_task(self._checkpoint_loop())
        logger.info("HiveMind initialized", session=self.session_id, workspace=str(self.workspace))

    async def _checkpoint_loop(self):
        while not self.shutdown_manager.is_shutting_down():
            try:
                await asyncio.sleep(settings.checkpoint_interval_seconds)
                state = {
                    "session_id": self.session_id,
                    "active_swarms": [s.id for s in self.active_swarms],
                    "statuses": {s.id: s.status for s in self.active_swarms},
                }
                await self.db.create_checkpoint(self.session_id, state)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("checkpoint failed", error=str(exc))

    async def _create_skill_requests(self, skill_requests: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        created = []
        for request in skill_requests:
            name = request.get("name")
            description = request.get("description", name or "generated skill")
            if name and self.registry.has(name):
                continue
            result = await self.skill_factory.create_skill(description, preferred_name=name)
            self.registry.load_user_skills()
            await self.db.record_skill(self.session_id, result["name"], result["description"], result["path"])
            created.append(result)
        return created

    async def _request_file_approvals(self, operations: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        approved: List[Dict[str, Any]] = []
        pending: List[Dict[str, Any]] = []
        for op in operations:
            require, risk, reason, scope = self.approvals.assess_file_operation(op, session_id=self.session_id)
            if require:
                pending.append(
                    await self.approvals.request(
                        ApprovalRequest(
                            session_id=self.session_id,
                            request_type="file_edit",
                            subject=op.get("path", "unknown"),
                            reason=reason,
                            risk_score=risk,
                            payload=op,
                            recommended_scope=scope,
                        )
                    )
                )
            else:
                approved.append(op)
        return approved, pending

    def _auto_validation_commands(self, work_root: Path, route: TaskRoute, task: Dict[str, Any], changed_files: List[str]) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        target_tests = [path for path in task.get("target_files", []) if str(path).startswith("tests/") or str(path).endswith("_test.py") or str(path).endswith("test.py")]
        target_tests.extend(self.repo_index.test_targets(changed_files + task.get("target_files", []), limit=8))
        target_tests = list(dict.fromkeys(target_tests))
        non_test_changed = [path for path in changed_files if not self._is_test_path(path)]
        changed_packages = {self.repo_index._package_name(path) for path in non_test_changed if path}
        should_run_full_pytest = (
            route.test_strategy == "full"
            and (
                not target_tests
                or len(target_tests) > 2
                or len(non_test_changed) > 2
                or len(changed_packages) > 2
            )
        )
        if route.test_strategy == "full" or route.lane == "repair":
            if (work_root / "tests").exists() or any(path.startswith("tests/") for path in changed_files + task.get("target_files", [])):
                if target_tests:
                    candidates.append({"command": f"pytest -q {' '.join(sorted(set(target_tests))[:8])}", "timeout": 180})
                if should_run_full_pytest:
                    candidates.append({"command": "pytest -q", "timeout": 240})
        if (work_root / "package.json").exists():
            candidates.append({"command": "npm test -- --runInBand", "timeout": 240})
        if (work_root / "Cargo.toml").exists():
            candidates.append({"command": "cargo test", "timeout": 240})
        if (work_root / "go.mod").exists():
            candidates.append({"command": "go test ./...", "timeout": 240})
        if (work_root / "pyproject.toml").exists() and changed_files:
            python_targets = [path for path in changed_files if path.endswith(".py")][:20]
            if python_targets:
                candidates.append({"command": "python -m compileall " + " ".join(sorted(python_targets)), "timeout": 180})
        seen: set[str] = set()
        deduped: List[Dict[str, Any]] = []
        for item in candidates:
            command = item.get("command")
            if command and command not in seen:
                deduped.append(item)
                seen.add(command)
        return deduped

    def _is_test_path(self, path: str) -> bool:
        normalized = str(path).replace("\\", "/")
        return normalized.startswith("tests/") or normalized.endswith("test.py") or normalized.endswith("_test.py")

    def _task_has_explicit_actions(self, task: Dict[str, Any]) -> bool:
        if task.get("commands"):
            return True
        skill_names = {
            str(item.get("name"))
            for item in (task.get("skill_requests") or [])
            if item.get("name")
        }
        if skill_names - {"read_file", "search_files"}:
            return True
        text = " ".join(
            [
                task.get("title", "") or "",
                task.get("objective", "") or "",
                " ".join(task.get("deliverables", []) or []),
            ]
        ).lower()
        return any(token in text for token in ["fix", "write", "update", "modify", "implement", "add", "create", "refactor", "rename", "rewrite", "change", "extend", "migrate"])

    def _task_requires_changes(self, task: Dict[str, Any], route: TaskRoute | None = None) -> bool:
        target_files = [str(path) for path in (task.get("target_files") or []) if path]
        if self._task_has_explicit_actions(task):
            return True
        if route and route.lane in {"repair", "refactor"} and target_files:
            return True
        return any(not path.startswith("tests/") for path in target_files)

    def _task_is_observation_only(self, task: Dict[str, Any]) -> bool:
        if task.get("commands"):
            return False
        skill_names = {
            str(item.get("name"))
            for item in (task.get("skill_requests") or [])
            if item.get("name")
        }
        if skill_names and skill_names - {"read_file", "search_files"}:
            return False
        if self._task_has_explicit_actions(task):
            return False
        text = " ".join(
            [
                task.get("title", "") or "",
                task.get("objective", "") or "",
                " ".join(task.get("deliverables", []) or []),
            ]
        ).lower()
        observation_tokens = ["inspect", "read", "analyze", "understand", "review", "evaluate", "gather", "research"]
        return bool(skill_names) or any(token in text for token in observation_tokens)

    def _extract_text_paths(self, text: str) -> list[str]:
        candidates: list[str] = []
        for match in re.findall(r"(?<!\w)([A-Za-z0-9_./\\-]+\.[A-Za-z0-9_]+)(?!\w)", text or ""):
            path = match.strip().strip("\"'`")
            if not path:
                continue
            if path.startswith(".") and "/" not in path and "\\" not in path:
                continue
            normalized = path.replace("\\", "/")
            if normalized not in candidates:
                candidates.append(normalized)
        return candidates

    def _augment_task_targets(self, task: Dict[str, Any], user_request: str) -> Dict[str, Any]:
        item = dict(task)
        merged: list[str] = [str(path) for path in (item.get("target_files") or []) if path]
        for text in [
            user_request,
            item.get("title", "") or "",
            item.get("objective", "") or "",
            " ".join(item.get("deliverables", []) or []),
        ]:
            for path in self._extract_text_paths(text):
                if path not in merged:
                    merged.append(path)
        if merged:
            item["target_files"] = merged
        return item

    def _selected_provider_name(self) -> str | None:
        diagnostics = getattr(self.provider, "diagnostics", None)
        if not callable(diagnostics):
            return None
        try:
            payload = diagnostics()
        except Exception:
            return None
        selected = str(payload.get("selected_provider") or "").strip().lower()
        if selected:
            return selected
        preferred = str(payload.get("preferred_provider") or "").strip().lower()
        return preferred or None

    def _is_local_model_path(self) -> bool:
        return self._selected_provider_name() == "ollama"

    def _normalize_user_request(self, user_request: str) -> str:
        request = (user_request or "").strip()
        lowered = request.lower()
        guidance: list[str] = []
        if any(token in lowered for token in ["fix", "bug", "broken", "make the tests pass", "repair"]):
            guidance.extend(
                [
                    "Use repo context to localize the most likely broken implementation files before editing.",
                    "Make the smallest safe fix first, then run the most relevant focused tests before finishing.",
                ]
            )
        if any(token in lowered for token in ["rename", "refactor", "migrate", "update callers", "roll out"]):
            guidance.extend(
                [
                    "Keep the behavior stable while updating all obvious callers and public entry points consistently.",
                    "Prefer focused validation over broad test noise unless the repo context suggests a wider blast radius.",
                ]
            )
        if any(token in lowered for token in ["summarize", "inspect", "review", "analyze", "understand"]):
            guidance.append("Prefer analysis over edits unless the user explicitly requested code changes.")
        if any(token in lowered for token in ["continue the last task", "continue last task", "continue the last session", "resume the last task"]):
            guidance.append("Look for the most recent session context and continue from that state instead of starting from scratch.")
        if self._is_local_model_path():
            guidance.append("The active model is local-first, so keep task decomposition tight, rely on repo signals heavily, and validate every concrete change.")
        if not guidance:
            return request
        bullet_list = "\n".join(f"- {item}" for item in dict.fromkeys(guidance))
        return f"{request}\n\nExecution guidance for VIKI:\n{bullet_list}"

    def _normalize_planned_tasks(self, tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for task in tasks:
            item = dict(task)
            subtasks = item.pop("subtasks", None) or []
            if subtasks:
                actionable_subtasks = [
                    child for child in subtasks
                    if self._task_has_explicit_actions(child) or child.get("target_files") or child.get("commands")
                ]
                if self._task_has_explicit_actions(item) or item.get("target_files") or item.get("commands") or item.get("deliverables"):
                    normalized.append(item)
                    continue
                if actionable_subtasks:
                    normalized.extend(actionable_subtasks)
                    continue
            normalized.append(item)
        if any(not self._task_is_observation_only(task) for task in normalized):
            normalized = [task for task in normalized if not self._task_is_observation_only(task)]
        return normalized or tasks

    def _task_is_validation_only(self, task: Dict[str, Any]) -> bool:
        commands = task.get("commands") or []
        if not commands:
            return False
        skill_names = {
            str(item.get("name"))
            for item in (task.get("skill_requests") or [])
            if item.get("name")
        }
        if skill_names and skill_names - {"run_command"}:
            return False
        target_files = [str(path).replace("\\", "/") for path in (task.get("target_files") or []) if path]
        non_test_targets = [
            path for path in target_files
            if not (path.startswith("tests/") or path.endswith("test.py") or path.endswith("_test.py"))
        ]
        deliverables = [str(item).lower() for item in (task.get("deliverables") or []) if item]
        text = " ".join(
            [
                task.get("title", "") or "",
                task.get("objective", "") or "",
                " ".join(task.get("deliverables", []) or []),
                " ".join(command.get("command", "") for command in commands),
            ]
        ).lower()
        validation_tokens = ["validate", "verification", "verify", "test", "pytest", "run tests", "run pytest", "check"]
        deliverables_are_validation = not deliverables or all(
            any(token in item for token in ["test", "validation", "verification", "output", "result", "log"])
            for item in deliverables
        )
        return (
            bool(any(token in text for token in validation_tokens))
            and not non_test_targets
            and deliverables_are_validation
        )

    def _merge_validation_tasks(self, tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        for task in tasks:
            item = dict(task)
            item["target_files"] = list(dict.fromkeys(str(path).replace("\\", "/") for path in (item.get("target_files") or []) if path))
            if merged and self._task_is_validation_only(item) and self._task_requires_changes(merged[-1]):
                previous = dict(merged[-1])
                existing_commands = previous.get("commands") or []
                seen = {command.get("command") for command in existing_commands if command.get("command")}
                for command in item.get("commands") or []:
                    if command.get("command") and command.get("command") not in seen:
                        existing_commands.append(command)
                        seen.add(command["command"])
                previous["commands"] = existing_commands
                previous_targets = previous.get("target_files") or []
                previous["target_files"] = list(dict.fromkeys(previous_targets + item.get("target_files", [])))
                merged[-1] = previous
                continue
            merged.append(item)
        return merged

    def _should_expand_task(self, task: Dict[str, Any], depth: int) -> bool:
        if not settings.enable_fractal_recursion or depth >= settings.max_swarm_depth:
            return False
        objective = str(task.get("objective", "") or "").strip()
        if len(objective) < 180:
            return False
        lowered = objective.lower()
        target_files = [str(path) for path in (task.get("target_files") or []) if path]
        multi_step_tokens = [
            "across the repo",
            "repo-wide",
            "monorepo",
            "multiple packages",
            "multiple files",
            "follow-up",
            "then",
            "after that",
            "roll out",
        ]
        if target_files and len(target_files) <= 2 and not any(token in lowered for token in multi_step_tokens):
            return False
        return True

    def _context_pack_limit(self, task: Dict[str, Any], route: TaskRoute) -> int:
        non_test_targets = [
            str(path).replace("\\", "/")
            for path in (task.get("target_files") or [])
            if path and not self._is_test_path(str(path))
        ]
        if route.cost_tier == "high-confidence" or route.isolation == "sandboxed-worktree":
            return 18
        if route.lane in {"repair", "refactor"} and len(non_test_targets) <= 2:
            return 10
        if len(non_test_targets) <= 1:
            return 8
        if len(non_test_targets) >= 4:
            return 16
        return 12

    def _docs_only_task(self, task: Dict[str, Any]) -> bool:
        deliverables = [str(item).replace("\\", "/") for item in (task.get("deliverables") or []) if item]
        doc_deliverables = [item for item in deliverables if Path(item).suffix.lower() in {".md", ".txt", ".rst"}]
        if deliverables and len(doc_deliverables) == len(deliverables):
            return True
        targets = [str(path).replace("\\", "/") for path in (task.get("target_files") or []) if path]
        if not targets:
            return False
        non_test_targets = [path for path in targets if not self._is_test_path(path)]
        if not non_test_targets:
            return False
        return all(Path(path).suffix.lower() in {".md", ".txt", ".rst"} for path in non_test_targets)

    def _primary_targets_are_docs(self, task: Dict[str, Any]) -> bool:
        deliverables = [str(item).replace("\\", "/") for item in (task.get("deliverables") or []) if item]
        doc_deliverables = [item for item in deliverables if Path(item).suffix.lower() in {".md", ".txt", ".rst"}]
        if deliverables and len(doc_deliverables) == len(deliverables):
            return True
        targets = [str(path).replace("\\", "/") for path in (task.get("target_files") or []) if path]
        if not targets:
            return False
        non_test_targets = [path for path in targets if not self._is_test_path(path)]
        if not non_test_targets:
            return False
        return all(Path(path).suffix.lower() in {".md", ".txt", ".rst"} for path in non_test_targets)

    def _candidate_model_hint(self, task: Dict[str, Any], route: TaskRoute) -> str:
        if self._docs_only_task(task):
            return "fast"
        if route.repair_focus == "policy-first":
            return "reasoning"
        return "coding"

    def _doc_target_files(self, task: Dict[str, Any]) -> List[str]:
        targets: List[str] = []
        for source in [task.get("target_files") or [], task.get("deliverables") or []]:
            for item in source:
                path = str(item).replace("\\", "/").strip()
                if path and Path(path).suffix.lower() in {".md", ".txt", ".rst"} and path not in targets:
                    targets.append(path)
        for text in [
            task.get("title", "") or "",
            task.get("objective", "") or "",
            " ".join(task.get("deliverables", []) or []),
        ]:
            for path in self._extract_text_paths(text):
                if Path(path).suffix.lower() in {".md", ".txt", ".rst"} and path not in targets:
                    targets.append(path)
        return targets

    def _is_validation_runbook_task(self, task: Dict[str, Any]) -> bool:
        if not self._docs_only_task(task):
            return False
        text = " ".join(
            [
                task.get("title", "") or "",
                task.get("objective", "") or "",
                " ".join(task.get("deliverables", []) or []),
                " ".join(self._doc_target_files(task)),
            ]
        ).lower()
        return any(token in text for token in ["runbook", "what to run", "validation command", "validation commands"])

    def _scan_repo_language_files(self, work_root: Path) -> Dict[str, List[str]]:
        ignored = {
            ".git",
            settings.workspace_dir,
            "node_modules",
            "dist",
            "build",
            "coverage",
            "__pycache__",
            ".venv",
            "venv",
        }
        groups: Dict[str, List[str]] = {"python": [], "typescript": [], "go": [], "python_tests": []}
        for path in work_root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(work_root)
            if any(part in ignored for part in relative.parts):
                continue
            rel = relative.as_posix()
            suffix = path.suffix.lower()
            if suffix == ".py":
                if rel.startswith("tests/") or rel.endswith("test.py") or rel.endswith("_test.py"):
                    groups["python_tests"].append(rel)
                else:
                    groups["python"].append(rel)
            elif suffix in {".ts", ".tsx"}:
                if not rel.endswith(".d.ts"):
                    groups["typescript"].append(rel)
            elif suffix == ".go":
                groups["go"].append(rel)
        for key in groups:
            groups[key] = sorted(groups[key])
        return groups

    def _synthesized_validation_commands(self, work_root: Path) -> Dict[str, str]:
        groups = self._scan_repo_language_files(work_root)
        commands: Dict[str, str] = {}
        if groups["python_tests"]:
            commands["Python"] = f"python -m pytest -q {' '.join(groups['python_tests'][:4])}"
        elif groups["python"]:
            primary = groups["python"][0]
            commands["Python"] = (
                'python -c "import py_compile; '
                f'py_compile.compile({json.dumps(primary)}, doraise=True); '
                'print(\'Python OK\')"'
            )
        if groups["typescript"]:
            commands["TypeScript"] = f"npx tsc --noEmit {groups['typescript'][0]}"
        if groups["go"]:
            main_go = next((path for path in groups["go"] if path.endswith("main.go")), "")
            commands["Go"] = f"go run {main_go}" if main_go else "go build"
        return commands

    def _build_validation_runbook_content(self, work_root: Path, repo_context: Dict[str, Any]) -> str:
        focus_entries = repo_context.get("focus", []) or []
        seen_paths: set[str] = set()
        rows: List[tuple[str, str, str]] = []
        for item in focus_entries:
            path = str(item.get("path", "") or "").replace("\\", "/")
            language = str(item.get("language", "") or "").strip()
            if not path or path in seen_paths or language not in {"python", "typescript", "go"}:
                continue
            summary = str(item.get("summary", "") or "").strip() or "Primary component"
            rows.append((path, language.title(), summary))
            seen_paths.add(path)
            if len(rows) >= 6:
                break
        if not rows:
            groups = self._scan_repo_language_files(work_root)
            for language_key, label in [("python", "Python"), ("typescript", "TypeScript"), ("go", "Go")]:
                for path in groups[language_key][:2]:
                    if path in seen_paths:
                        continue
                    rows.append((path, label, "Primary component"))
                    seen_paths.add(path)

        commands = self._synthesized_validation_commands(work_root)
        summary_languages = ", ".join(commands.keys()) if commands else "mixed-language"
        lines: List[str] = [
            "# Change Runbook",
            "",
            "## Repository Summary",
            f"This repository includes {summary_languages} components and should be validated with the commands below.",
            "",
            "## Key Files",
            "",
            "| File | Language | Purpose |",
            "|------|----------|---------|",
        ]
        for path, language, summary in rows:
            lines.append(f"| `{path}` | {language} | {summary} |")
        lines.extend(["", "## Validation Commands", ""])
        for language, command in commands.items():
            lines.extend(
                [
                    f"### {language}",
                    "",
                    "```bash",
                    command,
                    "```",
                    "",
                ]
            )
        if commands:
            lines.extend(["## Full Validation Sequence", "", "Run these commands in order:", "", "```bash"])
            for command in commands.values():
                lines.append(command)
            lines.extend(["```", ""])
        return "\n".join(lines).rstrip() + "\n"

    def _overlay_docs_operations(self, task: Dict[str, Any], repo_context: Dict[str, Any], work_root: Path, operations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not self._is_validation_runbook_task(task):
            return list(operations or [])
        doc_targets = self._doc_target_files(task)
        target_path = next((path for path in doc_targets if Path(path).name.lower() == "change_runbook.md"), doc_targets[0] if doc_targets else "CHANGE_RUNBOOK.md")
        content = self._build_validation_runbook_content(work_root, repo_context)
        filtered = [
            dict(item)
            for item in (operations or [])
            if str(item.get("path", "")).replace("\\", "/") != target_path
        ]
        filtered.append({"mode": "write", "path": target_path, "content": content})
        return filtered

    def _extract_structured_json(self, text: str) -> Dict[str, Any]:
        cleaned = (text or "").strip()
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.S)
        if fence_match:
            cleaned = fence_match.group(1)
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end >= start:
            cleaned = cleaned[start:end + 1]
        return json.loads(cleaned or "{}")

    def _sanitize_file_operations(self, executor: WorkspaceExecutor, operations: List[Dict[str, Any]]) -> tuple[list[Dict[str, Any]], list[str]]:
        valid: list[Dict[str, Any]] = []
        errors: list[str] = []
        for op in operations or []:
            try:
                valid.append(executor.validate_file_operation(dict(op)))
            except Exception as exc:
                path = op.get("path", "<unknown>")
                mode = op.get("mode", "write")
                errors.append(f"{mode}:{path}:{exc}")
        return valid, errors

    def _python_file_command(self, path: str) -> str:
        quoted_path = json.dumps(path)
        return (
            "python -c "
            + json.dumps(
                "from pathlib import Path; print(Path(" + quoted_path + ").read_text(encoding='utf-8'))"
            )
        )

    def _python_list_command(self, path: str = ".") -> str:
        quoted_path = json.dumps(path)
        return (
            "python -c "
            + json.dumps(
                "from pathlib import Path; print('\\n'.join(sorted(p.name for p in Path(" + quoted_path + ").iterdir())))"
            )
        )

    def _normalize_command_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        command = str(item.get("command") or "").strip()
        if not command:
            return item
        allowed, _ = self.security.validate_command(command)
        if allowed:
            return item
        normalized = dict(item)
        try:
            tokens = shlex.split(command, posix=False)
        except ValueError:
            return item
        if not tokens:
            return item
        head = tokens[0].lower()
        if head in {"type", "cat", "read_file", "get-content"} and len(tokens) >= 2:
            normalized["command"] = self._python_file_command(tokens[1].strip("\"'"))
            normalized["normalized_from"] = command
            return normalized
        if head in {"dir", "ls"}:
            target = tokens[1].strip("\"'") if len(tokens) >= 2 else "."
            normalized["command"] = self._python_list_command(target)
            normalized["normalized_from"] = command
            return normalized
        return item

    def _candidate_target_hits(self, task: Dict[str, Any], changed_files: List[str]) -> int:
        targets = self._task_targets(task)
        if not targets:
            return 0
        hits = 0
        for changed in changed_files:
            if changed in targets:
                hits += 1
                continue
            if any(changed.startswith(target.rstrip("/")) or target.startswith(changed.rstrip("/")) for target in targets):
                hits += 1
        return hits

    def _validation_successes(self, command_results: List[Dict[str, Any]]) -> int:
        interesting = ("pytest", "compileall", "go test", "cargo test", "npm test", "pnpm test", "yarn test")
        return len(
            [
                item for item in command_results
                if item.get("returncode") == 0 and any(token in str(item.get("command", "")) for token in interesting)
            ]
        )

    def _command_signature(self, command: str) -> str:
        return " ".join(str(command or "").split())

    def _filter_new_commands(self, commands: List[Dict[str, Any]], existing_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = {
            self._command_signature(item.get("effective_command") or item.get("command", ""))
            for item in existing_results
            if item.get("returncode") == 0 and (item.get("effective_command") or item.get("command"))
        }
        filtered: List[Dict[str, Any]] = []
        local_seen: set[str] = set()
        for item in commands or []:
            signature = self._command_signature(item.get("command", ""))
            if not signature or signature in seen or signature in local_seen:
                continue
            filtered.append(item)
            local_seen.add(signature)
        return filtered

    def _task_failures(self, task_results: List[Dict[str, Any]]) -> int:
        return sum(
            1
            for task in task_results
            for entry in task.get("command_results", [])
            if entry.get("returncode") not in (0, None)
        )

    def _should_skip_model_testing(self, changed_files: List[str], routes: List[TaskRoute], task_results: List[Dict[str, Any]]) -> bool:
        if not changed_files:
            return True
        if len(changed_files) > 3:
            return False
        if any(route.isolation == "sandboxed-worktree" for route in routes):
            return False
        if any(route.cost_tier == "high-confidence" for route in routes):
            return False
        if any(task.get("approvals") for task in task_results):
            return False
        if self._task_failures(task_results):
            return False
        validation_successes = sum(int(task.get("validation_successes", 0) or 0) for task in task_results)
        docs_only = all(Path(path).suffix.lower() in {".md", ".txt", ".rst"} for path in changed_files)
        return validation_successes > 0 or docs_only

    def _synthesize_testing_plan(
        self,
        user_request: str,
        changed_files: List[str],
        routes: List[TaskRoute],
        task_results: List[Dict[str, Any]],
        existing_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if self._should_skip_model_testing(changed_files, routes, task_results):
            return {
                "summary": "Skipped model-generated testing because task-level validation already covered the localized changes.",
                "commands": [],
                "expected_outputs": [],
                "source": "task-level-validation",
            }
        derived: List[Dict[str, Any]] = []
        target_tests = self.repo_index.test_targets(changed_files, limit=6)
        if target_tests and len(changed_files) <= 4:
            derived.append({"command": f"pytest -q {' '.join(target_tests[:4])}", "timeout": 180})
        derived = self._filter_new_commands(derived, existing_results)
        if derived:
            return {
                "summary": "Heuristic post-task validation derived from changed files and impacted tests.",
                "commands": derived,
                "expected_outputs": [],
                "source": "heuristic-targeted",
            }
        testing_swarm = SwarmPod(
            SwarmType.TESTING,
            f"Test changes for: {user_request}",
            self.provider,
            self.db,
            self.metrics,
            self.security,
            config=SwarmConfig(timeout_seconds=120),
            model_hint="fast",
        )
        self.active_swarms.append(testing_swarm)
        return {"_swarm": testing_swarm}

    def _should_skip_model_security(self, changed_files: List[str], routes: List[TaskRoute], task_results: List[Dict[str, Any]]) -> bool:
        if len(changed_files) > 4:
            return False
        if any(route.isolation == "sandboxed-worktree" for route in routes):
            return False
        if any(route.repair_focus in {"policy-first", "checkpointed"} for route in routes):
            return False
        if any(task.get("approvals") for task in task_results):
            return False
        return self._task_failures(task_results) == 0

    def _synthesize_security_plan(self, user_request: str, changed_files: List[str], routes: List[TaskRoute], task_results: List[Dict[str, Any]], existing_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        if self._should_skip_model_security(changed_files, routes, task_results):
            commands: List[Dict[str, Any]] = []
            python_targets = [path for path in changed_files if path.endswith(".py")][:12]
            if python_targets:
                commands.append({"command": "python -m compileall " + " ".join(sorted(python_targets)), "timeout": 180})
            commands = self._filter_new_commands(commands, existing_results)
            return {
                "summary": "Skipped model-driven security review for a localized low-risk change and relied on static scanning plus lightweight verification.",
                "issues": [],
                "recommended_commands": commands,
                "source": "static-and-heuristic",
            }
        security_swarm = SwarmPod(
            SwarmType.SECURITY,
            f"Audit changes for: {user_request}",
            self.provider,
            self.db,
            self.metrics,
            self.security,
            config=SwarmConfig(timeout_seconds=90),
            model_hint="reasoning",
        )
        self.active_swarms.append(security_swarm)
        return {"_swarm": security_swarm}

    async def _request_write_fallback(
        self,
        task: Dict[str, Any],
        route: TaskRoute,
        repo_context: Dict[str, Any],
        work_root: Path,
        failure_reason: str,
        prior_result: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        target_files = [str(path) for path in (task.get("target_files") or []) if path]
        rewrite_targets = [
            path for path in target_files
            if not path.startswith("tests/") and Path(path).suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".json"}
        ]
        if not rewrite_targets:
            rewrite_targets = [path for path in target_files if not path.startswith("tests/")]
        rewrite_targets = rewrite_targets[:3]
        if not rewrite_targets:
            return None

        files: list[Dict[str, str]] = []
        for path in rewrite_targets + list(repo_context.get("impact", {}).get("tests", []))[:2]:
            target = (work_root / path).resolve()
            if target.exists() and target.is_file():
                files.append(
                    {
                        "path": path,
                        "content": target.read_text(encoding="utf-8", errors="ignore")[:12000],
                    }
                )
        if not files:
            return None

        prompt = f"""
Objective: {task.get('objective') or task.get('title') or 'repair the requested files'}

Failure reason:
{failure_reason}

Allowed rewrite targets:
{json.dumps(rewrite_targets, indent=2)}

Suggested tests:
{json.dumps(repo_context.get('impact', {}).get('tests', []), indent=2)}

Prior candidate JSON:
{json.dumps(prior_result, indent=2)}

Current file contents:
{json.dumps(files, indent=2)}

Return JSON only.
Use a full-file write for simple fixes instead of replace_block when matching is uncertain.
Do not emit no-op edits.
Schema requirements:
{CODING_SCHEMA}
""".strip()
        response = await self.provider.complete(
            self._candidate_model_hint(task, route),
            [
                {"role": "system", "content": "You are VIKI coding swarm rewrite fallback. Respond with strict JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=6000,
            timeout=max(180, settings.max_execution_time_seconds),
        )
        try:
            return self._extract_structured_json(response.get("content", "{}"))
        except Exception:
            return None

    def _task_targets(self, task: Dict[str, Any]) -> set[str]:
        return {str(path) for path in task.get("target_files", []) if path}

    def _backfill_task_targets(self, task: Dict[str, Any], repo_context: Dict[str, Any]) -> Dict[str, Any]:
        item = dict(task)
        existing = [str(path).replace("\\", "/") for path in (item.get("target_files") or []) if path]
        merged = list(dict.fromkeys(existing))
        if self._primary_targets_are_docs(item):
            item["target_files"] = merged
            return item
        has_non_test_target = any(not self._is_test_path(path) and Path(path).suffix not in {".md", ".rst", ".txt"} for path in merged)
        if not has_non_test_target:
            text = " ".join(
                [
                    item.get("title", "") or "",
                    item.get("objective", "") or "",
                    " ".join(item.get("deliverables", []) or []),
                ]
            ).lower()
            prefers_callers = any(token in text for token in ["migrate", "migration", "replace", "rename", "switch", "move to", "new api"])
            focus_items = list(repo_context.get("focus", []))
            if prefers_callers:
                focus_items = sorted(
                    focus_items,
                    key=lambda focus_item: (
                        -int(bool(focus_item.get("imports"))),
                        str(focus_item.get("path", "")),
                    ),
                )
            for focus_item in focus_items:
                path = str(focus_item.get("path", "") or "").replace("\\", "/")
                if not path or self._is_test_path(path) or Path(path).suffix in {".md", ".rst", ".txt"}:
                    continue
                merged.append(path)
                if len([entry for entry in merged if not self._is_test_path(entry)]) >= 2:
                    break
        if not any(self._is_test_path(path) for path in merged):
            for test_path in repo_context.get("impact", {}).get("tests", [])[:4]:
                merged.append(str(test_path).replace("\\", "/"))
        merged = list(dict.fromkeys(merged))
        if merged:
            item["target_files"] = merged
        return item

    def _tasks_conflict(self, left: Dict[str, Any], right: Dict[str, Any]) -> bool:
        left_targets = self._task_targets(left)
        right_targets = self._task_targets(right)
        if not left_targets or not right_targets:
            return False
        if left_targets & right_targets:
            return True
        for lpath in left_targets:
            for rpath in right_targets:
                if lpath.startswith(rpath.rstrip("/")) or rpath.startswith(lpath.rstrip("/")):
                    return True
        return False

    async def _execute_tasks(self, tasks: List[Dict[str, Any]], routes: List[TaskRoute], context: Dict[str, Any]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        semaphore = asyncio.Semaphore(max(1, settings.max_parallel_swarms))

        async def run_safe(task: Dict[str, Any], route: TaskRoute) -> Dict[str, Any]:
            async with semaphore:
                return await self._execute_task(task, context, route)

        async def flush(batch: List[tuple[Dict[str, Any], TaskRoute]]) -> None:
            nonlocal results
            if not batch:
                return
            results.extend(await asyncio.gather(*(run_safe(task, route) for task, route in batch)))
            batch.clear()

        safe_batch: List[tuple[Dict[str, Any], TaskRoute]] = []
        for task, route in zip(tasks, routes):
            if not route.parallel_safe:
                await flush(safe_batch)
                results.append(await self._execute_task(task, context, route))
                continue
            if any(self._tasks_conflict(task, pending_task) for pending_task, _ in safe_batch):
                await flush(safe_batch)
            safe_batch.append((task, route))
        await flush(safe_batch)
        return results

    async def _run_command_batch(self, commands: List[Dict[str, Any]], root: str | Path | None = None, executor: WorkspaceExecutor | None = None, network_enabled: bool | None = None, labels: Dict[str, str] | None = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        results = []
        approvals = []
        command_executor = executor or self.executor
        seen_commands: set[str] = set()
        for item in commands:
            normalized_item = self._normalize_command_item(dict(item))
            command = normalized_item.get("command")
            if not command:
                continue
            signature = command.strip()
            if signature in seen_commands:
                continue
            seen_commands.add(signature)
            require, risk, reason, scope = self.approvals.assess_command(command, session_id=self.session_id)
            if require:
                approvals.append(
                    await self.approvals.request(
                        ApprovalRequest(
                            session_id=self.session_id,
                            request_type="command",
                            subject=command,
                            reason=reason,
                            risk_score=risk,
                            payload=normalized_item,
                            recommended_scope=scope,
                        )
                    )
                )
                continue
            result = command_executor.run_command(
                command,
                int(normalized_item.get("timeout", settings.max_execution_time_seconds)),
                root=root,
                network_enabled=network_enabled,
                labels=labels,
            )
            if normalized_item.get("normalized_from"):
                result["normalized_from"] = normalized_item["normalized_from"]
            await self.db.record_command(self.session_id, str(item.get("command", command)), result)
            results.append(result)
        return results, approvals

    async def _expand_tasks(self, tasks: List[Dict[str, Any]], context: Dict[str, Any], depth: int = 0) -> List[Dict[str, Any]]:
        if not settings.enable_fractal_recursion or depth >= settings.max_swarm_depth:
            return tasks
        expanded: List[Dict[str, Any]] = []
        for task in tasks:
            subtasks = task.get("subtasks") or []
            if subtasks:
                nested = [{**child, "depth": depth + 1} for child in subtasks]
                expanded.extend(await self._expand_tasks(nested, context, depth + 1))
                continue
            if self._should_expand_task(task, depth + 1):
                child_swarm = SwarmPod(
                    SwarmType.PLANNING,
                    f"Decompose task: {task['objective']}",
                    self.provider,
                    self.db,
                    self.metrics,
                    self.security,
                    depth=depth + 1,
                    config=SwarmConfig(timeout_seconds=90),
                    model_hint="reasoning",
                )
                self.active_swarms.append(child_swarm)
                child_plan = await child_swarm.run_structured(self.session_id, {**context, "task": task}, PLANNING_SCHEMA)
                child_tasks = child_plan.get("tasks") or []
                if child_tasks:
                    expanded.extend(await self._expand_tasks(child_tasks, context, depth + 1))
                    continue
            expanded.append({**task, "depth": depth})
        return expanded

    async def _repair_loop(
        self,
        task: Dict[str, Any],
        route: TaskRoute,
        command_results: List[Dict[str, Any]],
        changed_files: List[str],
        work_root: Path,
        context: Dict[str, Any],
        work_executor: WorkspaceExecutor,
    ) -> Tuple[List[str], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        approvals: List[Dict[str, Any]] = []
        repairs: List[Dict[str, Any]] = []
        current_failures = [entry for entry in command_results if entry.get("returncode") not in (0, None)]
        for _ in range(settings.max_repair_attempts):
            if not current_failures:
                break
            failure_analysis = self.failure_classifier.summarize(current_failures)
            impact = self.repo_index.impact_report(changed_files + task.get("target_files", []), limit=16)
            snapshot = self.failure_classifier.snapshot_files(work_root, changed_files)
            repair_swarm = SwarmPod(
                SwarmType.DEBUGGING,
                f"Repair failing task: {task.get('title') or task.get('objective')}",
                self.provider,
                self.db,
                self.metrics,
                self.security,
                config=SwarmConfig(timeout_seconds=120),
                model_hint="reasoning" if route.repair_focus in {"root-cause", "checkpointed", "policy-first"} else route.model,
            )
            self.active_swarms.append(repair_swarm)
            repair_plan = await repair_swarm.run_structured(
                self.session_id,
                {
                    **context,
                    "task": task,
                    "changed_files": changed_files,
                    "failures": current_failures,
                    "failure_analysis": failure_analysis,
                    "impact": impact,
                    "repo_symbols": self.repo_index.symbols(paths=impact.get("changed_files", []) + impact.get("neighbors", []), limit=24),
                    "route": route.to_dict(),
                },
                REPAIR_SCHEMA,
            )
            repairs.append({**repair_plan, "failure_analysis": failure_analysis, "impact": impact})
            approved_ops, file_approvals = await self._request_file_approvals(repair_plan.get("file_operations", []))
            approvals.extend(file_approvals)
            changed_files.extend(work_executor.apply_file_operations(approved_ops))
            rerun_commands = repair_plan.get("commands") or self.failure_classifier.targeted_rerun_commands(current_failures, changed_files)
            rerun_results, command_approvals = await self._run_command_batch(
                rerun_commands,
                root=work_root,
                executor=work_executor,
                network_enabled=(route.isolation == "sandboxed-worktree" and settings.sandbox_network_enabled),
                labels={"session": self.session_id, "task": str(task.get("id", "task")), "phase": "repair"},
            )
            approvals.extend(command_approvals)
            command_results.extend(rerun_results)
            if rerun_results and not self.failure_classifier.improved(current_failures, rerun_results):
                restored = self.failure_classifier.restore_snapshot(work_root, snapshot)
                await self.db.audit_log(
                    "INFO",
                    "repair",
                    "ROLLBACK_AFTER_NON_IMPROVING_REPAIR",
                    details={"task_id": task.get("id"), "route": route.to_dict(), "restored": restored},
                )
            current_failures = [entry for entry in rerun_results if entry.get("returncode") not in (0, None)] if rerun_results else current_failures
        return sorted(set(changed_files)), command_results, approvals, repairs

    def _candidate_count(self, route: TaskRoute, task: Dict[str, Any], repo_context: Dict[str, Any]) -> int:
        non_test_targets = [path for path in (task.get("target_files") or []) if path and not self._is_test_path(str(path))]
        neighbors = repo_context.get("impact", {}).get("neighbors", []) or []
        if route.lane == "repair":
            if len(non_test_targets) <= 1 and len(neighbors) <= 2:
                return 2 if self._is_local_model_path() else 1
            base = 2 if len(non_test_targets) <= 2 and len(neighbors) <= 3 else 3
            return min(3, base + (1 if self._is_local_model_path() and base < 3 else 0))
        if route.lane == "refactor":
            base = 1 if len(non_test_targets) <= 2 and len(neighbors) <= 3 else 2
            return min(3, base + (1 if self._is_local_model_path() and base < 2 else 0))
        if route.cost_tier == "high-confidence":
            return 1 if len(non_test_targets) <= 2 else 2
        if len(task.get("target_files", []) or []) >= 5:
            return 2
        return 1

    def _candidate_confidence(
        self,
        task: Dict[str, Any],
        route: TaskRoute,
        command_results: List[Dict[str, Any]],
        approvals: List[Dict[str, Any]],
        changed_files: List[str],
        repairs: List[Dict[str, Any]],
    ) -> float:
        failures = len([entry for entry in command_results if entry.get("returncode") not in (0, None)])
        succeeded = len([entry for entry in command_results if entry.get("returncode") == 0])
        score = 0.2
        if failures == 0:
            score += 0.35
        else:
            score -= min(0.3, failures * 0.12)
        if approvals:
            score -= min(0.2, len(approvals) * 0.05)
        if succeeded:
            score += min(0.15, succeeded * 0.05)
        if route.test_strategy == "full":
            score += 0.1
        if repairs and failures == 0:
            score += 0.1
        if len(changed_files) <= 5:
            score += 0.05
        required_change = self._task_requires_changes(task, route)
        target_hits = self._candidate_target_hits(task, changed_files)
        validation_successes = self._validation_successes(command_results)
        if required_change and not changed_files:
            score -= 0.45
        elif required_change and target_hits:
            score += min(0.18, target_hits * 0.09)
        if validation_successes:
            score += min(0.18, validation_successes * 0.08)
        return max(0.0, min(1.0, round(score, 3)))

    def _candidate_sort_key(self, candidate: Dict[str, Any]) -> tuple[int, int, int, int, int, float, int]:
        failures = len([entry for entry in candidate.get("command_results", []) if entry.get("returncode") not in (0, None)])
        approvals = len(candidate.get("approvals", []))
        noop_penalty = 1 if candidate.get("required_change") and not candidate.get("candidate_changed_files") else 0
        validation_successes = int(candidate.get("validation_successes", 0) or 0)
        target_hits = int(candidate.get("target_hit_count", 0) or 0)
        confidence = float(candidate.get("confidence", 0.0) or 0.0)
        changed = len(candidate.get("candidate_changed_files", []))
        return (noop_penalty, failures, approvals, -validation_successes, -target_hits, -confidence, -changed)

    def _acceptance_threshold(self, task: Dict[str, Any], route: TaskRoute, candidate: Dict[str, Any]) -> float:
        threshold = 0.55
        if self._task_requires_changes(task, route) and int(candidate.get("target_hit_count", 0) or 0) > 0:
            threshold = 0.4
        if int(candidate.get("validation_successes", 0) or 0) > 0 and candidate.get("candidate_changed_files"):
            threshold = min(threshold, 0.35)
        return threshold

    async def _execute_candidate(
        self,
        task: Dict[str, Any],
        context: Dict[str, Any],
        route: TaskRoute,
        candidate_index: int,
        repo_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        candidate_id = f"{task.get('id', 'task')}-c{candidate_index}"
        coding_swarm = SwarmPod(
            SwarmType.CODING,
            f"{task.get('objective', task.get('title', 'coding task'))} (candidate {candidate_index})",
            self.provider,
            self.db,
            self.metrics,
            self.security,
            config=SwarmConfig(timeout_seconds=180),
            model_hint=self._candidate_model_hint(task, route),
        )
        self.active_swarms.append(coding_swarm)
        worktree = self.worktrees.create(candidate_id)
        work_executor = WorkspaceExecutor(worktree.root, security=self.security, sandbox=self.sandbox)
        result = await coding_swarm.run_structured(
            self.session_id,
            {
                **context,
                "task": task,
                "candidate": {"id": candidate_id, "index": candidate_index, "strategy": "primary" if candidate_index == 1 else "alternative"},
                "isolated_workspace": str(worktree.root),
                "route": route.to_dict(),
                "repo_context": repo_context,
                "repo_focus": repo_context.get("focus", []),
                "repo_neighbors": repo_context.get("impact", {}).get("neighbors", []),
                "suggested_tests": repo_context.get("impact", {}).get("tests", []),
                "repo_instructions": repo_context.get("instructions", []),
                "repo_snippets": repo_context.get("snippets", []),
            },
            CODING_SCHEMA,
        )
        created_skills: list[dict[str, Any]] = []
        approvals: list[dict[str, Any]] = []
        changed_files: list[str] = []
        command_results: list[dict[str, Any]] = []
        repairs: list[dict[str, Any]] = []
        diff_preview: list[dict[str, Any]] = []
        patch_bundle_path = None
        rollback_bundle_path = None
        execution_error = None
        fallback_used = False
        fallback_errors: list[str] = []
        try:
            created_skills = await self._create_skill_requests(result.get("skill_requests", []))
            planned_operations = self._overlay_docs_operations(
                task,
                repo_context,
                worktree.root,
                result.get("file_operations", []),
            )
            file_operations, invalid_ops = self._sanitize_file_operations(work_executor, planned_operations)
            fallback_errors.extend(invalid_ops)
            if self._task_requires_changes(task, route) and (not file_operations or invalid_ops):
                fallback = await self._request_write_fallback(
                    task,
                    route,
                    repo_context,
                    worktree.root,
                    "; ".join(invalid_ops) or "no actionable file operations",
                    result,
                )
                if fallback:
                    result = fallback
                    fallback_used = True
                    planned_operations = self._overlay_docs_operations(
                        task,
                        repo_context,
                        worktree.root,
                        result.get("file_operations", []),
                    )
                    file_operations, fallback_invalid = self._sanitize_file_operations(work_executor, planned_operations)
                    fallback_errors.extend(fallback_invalid)
            approved_ops, approvals = await self._request_file_approvals(file_operations)
            if self._task_requires_changes(task, route) and not approved_ops and not approvals:
                raise ValueError("; ".join(fallback_errors) if fallback_errors else "no actionable file operations after normalization")
            snapshot = self.failure_classifier.snapshot_files(worktree.root, [op.get("path", "") for op in approved_ops if op.get("path")])
            try:
                changed_files = work_executor.apply_file_operations(approved_ops)
            except Exception as exc:
                if self._task_requires_changes(task, route) and not fallback_used:
                    self.failure_classifier.restore_snapshot(worktree.root, snapshot)
                    fallback = await self._request_write_fallback(task, route, repo_context, worktree.root, str(exc), result)
                    if fallback:
                        result = fallback
                        fallback_used = True
                        file_operations, fallback_invalid = self._sanitize_file_operations(work_executor, result.get("file_operations", []))
                        fallback_errors.extend(fallback_invalid)
                        approved_ops, approvals = await self._request_file_approvals(file_operations)
                        changed_files = work_executor.apply_file_operations(approved_ops)
                    else:
                        raise
                else:
                    raise
            if self._docs_only_task(task):
                requested_commands = []
            else:
                requested_commands = result.get("commands") or task.get("commands") or self._auto_validation_commands(worktree.root, route, task, changed_files)
            command_results, command_approvals = await self._run_command_batch(
                requested_commands,
                root=worktree.root,
                executor=work_executor,
                network_enabled=(route.isolation == "sandboxed-worktree" and settings.sandbox_network_enabled),
                labels={"session": self.session_id, "task": str(task.get("id", "task")), "phase": "validate"},
            )
            approvals.extend(command_approvals)
            changed_files, command_results, repair_approvals, repairs = await self._repair_loop(task, route, command_results, changed_files, worktree.root, context, work_executor)
            approvals.extend(repair_approvals)
            diff_preview = self.worktrees.diff_preview(worktree.root, changed_files, max_preview_lines=80)
            if changed_files:
                patch_bundle_path = str(
                    self.worktrees.export_patch_bundle(
                        worktree.root,
                        changed_files,
                        self.workspace / settings.runs_dir / f"{self.session_id}-{candidate_id}.patch",
                    )
                )
                rollback_bundle_path = str(
                    self.worktrees.export_rollback_bundle(
                        worktree.root,
                        changed_files,
                        self.workspace / settings.runs_dir / f"{self.session_id}-{candidate_id}-rollback.patch",
                    )
                )
        except Exception as exc:
            execution_error = self.security.redact_text(str(exc))
            command_results = [
                {
                    "returncode": 1,
                    "output": "",
                    "error": execution_error,
                    "command": "candidate_execution",
                    "cwd": str(worktree.root),
                    "runtime": "local",
                    "sandboxed": False,
                }
            ]
        failures = [entry for entry in command_results if entry.get("returncode") not in (0, None)]
        target_hit_count = self._candidate_target_hits(task, changed_files)
        validation_successes = self._validation_successes(command_results)
        required_change = self._task_requires_changes(task, route)
        confidence = self._candidate_confidence(task, route, command_results, approvals, changed_files, repairs)
        candidate_result = {
            "task": task,
            "candidate": candidate_id,
            "route": route.to_dict(),
            "result": result,
            "repairs": repairs,
            "changed_files": [],
            "candidate_changed_files": sorted(set(changed_files)),
            "command_results": command_results,
            "approvals": approvals,
            "created_skills": created_skills,
            "diff_preview": diff_preview,
            "patch_bundle": patch_bundle_path,
            "rollback_bundle": rollback_bundle_path,
            "worktree": {"root": str(worktree.root), "mode": worktree.mode, "requested_isolation": route.isolation},
            "sync": {"status": "candidate_ready", "copied": [], "deleted": []},
            "confidence": confidence,
            "required_change": required_change,
            "target_hit_count": target_hit_count,
            "validation_successes": validation_successes,
            "evidence": {
                "failure_count": len(failures),
                "approval_count": len(approvals),
                "changed_file_count": len(changed_files),
                "repair_attempts": len(repairs),
                "repo_impact": repo_context.get("impact", {}),
            },
        }
        if execution_error:
            candidate_result["execution_error"] = execution_error
        if fallback_used or fallback_errors:
            candidate_result["normalization"] = {
                "fallback_used": fallback_used,
                "errors": fallback_errors,
            }
        return candidate_result

    async def _execute_task(self, task: Dict[str, Any], context: Dict[str, Any], route: TaskRoute) -> Dict[str, Any]:
        repo_context = self.repo_index.context_pack(
            " ".join([task.get("title", ""), task.get("objective", "")]),
            target_files=task.get("target_files", []),
            limit=self._context_pack_limit(task, route),
        )
        task = self._backfill_task_targets(task, repo_context)
        candidate_total = self._candidate_count(route, task, repo_context)
        candidates = await asyncio.gather(
            *(self._execute_candidate(task, context, route, index, repo_context) for index in range(1, candidate_total + 1))
        )
        candidates = sorted(candidates, key=self._candidate_sort_key)
        winner = candidates[0]
        failures = [entry for entry in winner.get("command_results", []) if entry.get("returncode") not in (0, None)]
        sync_report = {"copied": [], "deleted": []}
        threshold = self._acceptance_threshold(task, route, winner)
        if (
            winner.get("candidate_changed_files")
            and not winner.get("approvals")
            and not failures
            and (not winner.get("required_change") or int(winner.get("target_hit_count", 0) or 0) > 0)
            and float(winner.get("confidence", 0.0) or 0.0) >= threshold
        ):
            sync_report = self.worktrees.sync_back(Path(winner["worktree"]["root"]), winner["candidate_changed_files"])
            winner["changed_files"] = sync_report.get("copied", []) + sync_report.get("deleted", [])
            winner["sync"] = {"status": "committed", **sync_report}
            selection_status = "accepted"
        elif winner.get("approvals"):
            winner["sync"] = {"status": "awaiting_approval", **sync_report}
            selection_status = "rejected_for_approval"
        elif failures:
            winner["sync"] = {"status": "kept_isolated_due_to_failures", **sync_report}
            selection_status = "rejected_for_failures"
        else:
            winner["sync"] = {"status": "kept_isolated_due_to_low_confidence", **sync_report}
            selection_status = "rejected_for_low_confidence"

        winner["task_ledger"] = {
            "task_id": task.get("id"),
            "route": route.to_dict(),
            "repo_context": repo_context,
            "selection": {
                "status": selection_status,
                "winner": winner.get("candidate"),
                "candidates": [
                    {
                        "candidate": item.get("candidate"),
                        "confidence": item.get("confidence"),
                        "failure_count": len([entry for entry in item.get("command_results", []) if entry.get("returncode") not in (0, None)]),
                        "approval_count": len(item.get("approvals", [])),
                        "changed_files": item.get("candidate_changed_files", []),
                    }
                    for item in candidates
                ],
            },
        }
        winner["candidates"] = [
            {
                "candidate": item.get("candidate"),
                "confidence": item.get("confidence"),
                "patch_bundle": item.get("patch_bundle"),
                "rollback_bundle": item.get("rollback_bundle"),
                "sync_status": item.get("sync", {}).get("status"),
                "changed_files": item.get("candidate_changed_files", []),
            }
            for item in candidates
        ]
        return winner

    async def process_request(self, user_request: str, mode: str = "standard") -> Dict[str, Any]:
        await self.rate_limiter.acquire()
        branch_name = f"viki-{self.session_id}"
        normalized_request = self._normalize_user_request(user_request)
        recent_memories = await self.memory.recall(limit=12)
        recent_failures = await self.db.recent_command_failures(limit=8)
        repo_profile = self.repo_index.profile()
        repo_focus = self.repo_index.focus(normalized_request, limit=40)
        repo_instructions = self.repo_index.instructions(limit=4)
        base_context = {
            "request": normalized_request,
            "original_request": user_request,
            "mode": mode,
            "workspace": str(self.workspace),
            "available_skills": [record.name for record in self.registry.list_skills()],
            "existing_files": [item["path"] for item in repo_focus] if repo_profile.get("large_repo") else [
                str(path.relative_to(self.workspace))
                for path in self.workspace.rglob("*")
                if path.is_file() and settings.workspace_dir not in path.parts
            ],
            "repo_profile": repo_profile,
            "repo_focus": repo_focus,
            "repo_instructions": repo_instructions,
            "recent_memories": recent_memories,
            "recent_failures": recent_failures,
        }
        context = self.compressor.compress(base_context)
        await self.db.create_session(self.session_id, user_request, branch_name, {"mode": mode, **context})

        plan_swarm = SwarmPod(
            SwarmType.PLANNING,
            f"Plan execution for: {normalized_request}",
            self.provider,
            self.db,
            self.metrics,
            self.security,
            config=SwarmConfig(timeout_seconds=120),
            model_hint="reasoning",
        )
        self.active_swarms.append(plan_swarm)
        plan = await plan_swarm.run_structured(self.session_id, context, PLANNING_SCHEMA)

        tasks = plan.get("tasks") or [
            {
                "id": "task-1",
                "title": user_request,
                "objective": normalized_request,
                "target_files": [],
                "deliverables": [],
                "commands": plan.get("testing_commands", []),
                "skill_requests": [],
            }
        ]
        tasks = self._normalize_planned_tasks(tasks)
        tasks = [self._augment_task_targets(task, normalized_request) for task in tasks]
        tasks = await self._expand_tasks(tasks, context)
        tasks = [self._augment_task_targets(task, normalized_request) for task in tasks]
        tasks = self._merge_validation_tasks(tasks)
        routes = self.router.route_tasks(normalized_request, tasks, context)
        task_results = await self._execute_tasks(tasks, routes, context)

        changed_files = sorted({path for item in task_results for path in item["changed_files"]})
        command_results = [entry for item in task_results for entry in item["command_results"]]
        pending_approvals = [entry for item in task_results for entry in item["approvals"]]
        created_skills = [entry for item in task_results for entry in item["created_skills"]]
        diff_preview = [entry for item in task_results for entry in item.get("diff_preview", [])][:12]
        patch_bundles = [item.get("patch_bundle") for item in task_results if item.get("patch_bundle")]
        coding_results = [item["result"] for item in task_results]
        merged_operations = self.merge_resolver.combine_operations([item["result"].get("file_operations", []) for item in task_results])

        testing_plan = self._synthesize_testing_plan(normalized_request, changed_files, routes, task_results, command_results)
        if testing_plan.get("_swarm"):
            testing_swarm = testing_plan.pop("_swarm")
            testing_plan = await testing_swarm.run_structured(
                self.session_id,
                {**context, "changed_files": changed_files, "plan": plan, "routes": [route.to_dict() for route in routes]},
                TESTING_SCHEMA,
            )
        testing_results, testing_approvals = await self._run_command_batch(
            self._filter_new_commands(testing_plan.get("commands", []), command_results),
            root=self.workspace,
            labels={"session": self.session_id, "phase": "testing"},
        )
        command_results.extend(testing_results)
        pending_approvals.extend(testing_approvals)

        security_plan = self._synthesize_security_plan(normalized_request, changed_files, routes, task_results, command_results)
        if security_plan.get("_swarm"):
            security_swarm = security_plan.pop("_swarm")
            security_plan = await security_swarm.run_structured(self.session_id, {**context, "changed_files": changed_files}, SECURITY_SCHEMA)
        security_results, security_approvals = await self._run_command_batch(
            self._filter_new_commands(security_plan.get("recommended_commands", []), command_results),
            root=self.workspace,
            labels={"session": self.session_id, "phase": "security"},
        )
        command_results.extend(security_results)
        pending_approvals.extend(security_approvals)

        changed_file_map = {}
        for relative in changed_files:
            path = self.workspace / relative
            if path.exists() and path.is_file():
                changed_file_map[relative] = path.read_text(encoding="utf-8", errors="ignore")

        secure, security_findings = self.security.scan_file_changes(changed_file_map)
        if not secure:
            await self.db.audit_log("WARNING", "security", "FILE_SCAN_FAILED", details=security_findings)

        await self.memory.remember(
            self.session_id,
            "session_summary",
            {
                "request": user_request,
                "normalized_request": normalized_request,
                "status": "completed" if secure else "completed_with_security_findings",
                "changed_files": changed_files,
            "repo_profile": repo_profile,
            "repo_focus": repo_focus,
                "approvals": len(pending_approvals),
                "routes": [route.to_dict() for route in routes],
            },
        )

        final_result = {
            "session_id": self.session_id,
            "status": "completed" if secure else "completed_with_security_findings",
            "request": user_request,
            "normalized_request": normalized_request,
            "branch": branch_name,
            "plan": plan,
            "tasks": tasks,
            "routes": [route.to_dict() for route in routes],
            "task_results": task_results,
            "coding_results": coding_results,
            "testing": testing_plan,
            "security": {"model_findings": security_plan, "static_findings": security_findings},
            "repair_summary": self.failure_classifier.summarize(command_results),
            "changed_files": changed_files,
            "diff_preview": diff_preview,
            "patch_bundles": patch_bundles,
            "repo_profile": repo_profile,
            "repo_focus": repo_focus,
            "repo_instructions": repo_instructions,
            "commands": command_results,
            "created_skills": created_skills,
            "pending_approvals": pending_approvals,
            "merge_summary": merged_operations,
            "isolated_workspaces": [item["worktree"] for item in task_results],
            "task_ledgers": [item.get("task_ledger") for item in task_results if item.get("task_ledger")],
            "candidate_summary": [item.get("candidates", []) for item in task_results],
        }
        await self.db.update_session(self.session_id, final_result["status"], final_result)
        return final_result

    async def resume_last_session(self) -> Dict[str, Any]:
        latest = await self.db.get_latest_session()
        checkpoint = await self.db.get_latest_checkpoint(latest["id"] if latest else None)
        return {"session": latest, "checkpoint": checkpoint}

    async def shutdown(self) -> None:
        await self._cleanup()

    async def _cleanup(self):
        if self._checkpoint_task is not None:
            self._checkpoint_task.cancel()
            try:
                await self._checkpoint_task
            except asyncio.CancelledError:
                pass
        for swarm in self.active_swarms:
            if swarm.status not in {"completed", "cancelled"}:
                await swarm.cancel()
        self.worktrees.cleanup()
        self.sandbox.cleanup()
