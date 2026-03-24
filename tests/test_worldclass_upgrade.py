from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from viki.api.server import create_app
from viki.core.actions import WorkspaceExecutor
from viki.core.hive import HiveMind
from viki.core.routing import TaskRoute
from viki.evals.live_suite import LiveExecutionSuite
from viki.evals.scripted_provider import ScriptedEvalProvider
from viki.evals.stress import generate_stress_repos
from viki.ide.vscode import VSCodeIntegrator
from viki.providers.litellm_provider import LiteLLMProvider


class RepairProvider:
    def validate_config(self):
        return True

    def get_available_models(self):
        return ["repair/reasoning", "repair/coding"]

    async def complete(self, model, messages, **kwargs):
        system = messages[0]["content"].lower()
        if "planning swarm" in system:
            content = json.dumps(
                {
                    "goal": "fix auth bug",
                    "summary": "repair task",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "fix auth bug",
                            "objective": "fix auth bug",
                            "target_files": ["app/auth.py", "tests/test_auth.py"],
                            "deliverables": ["bugfix"],
                            "commands": [],
                            "skill_requests": [],
                        }
                    ],
                    "testing_commands": [],
                    "acceptance_criteria": ["tests green"],
                }
            )
        elif "coding swarm" in system:
            content = json.dumps(
                {
                    "task_id": "task-1",
                    "summary": "candidate patch",
                    "file_operations": [{"mode": "write", "path": "app/auth.py", "content": "value = 'fixed'\n"}],
                    "commands": [{"command": "python -c \"print('ok')\"", "timeout": 30}],
                    "skill_requests": [],
                    "notes": [],
                }
            )
        elif "testing swarm" in system:
            content = json.dumps({"summary": "tests ok", "commands": [], "expected_outputs": []})
        elif "debugging swarm" in system:
            content = json.dumps({"summary": "no repair", "root_cause": "none", "file_operations": [], "commands": [], "notes": []})
        else:
            content = json.dumps({"summary": "security ok", "issues": [], "recommended_commands": []})
        return {"content": content, "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, "model": model, "provider": "repair"}


class ReplaceBlockFailureProvider:
    def validate_config(self):
        return True

    def get_available_models(self):
        return ["repair/reasoning", "repair/coding"]

    async def complete(self, model, messages, **kwargs):
        system = messages[0]["content"].lower()
        if "planning swarm" in system:
            content = json.dumps(
                {
                    "goal": "fix auth bug",
                    "summary": "repair task",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "fix auth bug",
                            "objective": "fix auth bug",
                            "target_files": ["app/auth.py"],
                            "deliverables": ["bugfix"],
                            "commands": [],
                            "skill_requests": [],
                        }
                    ],
                    "testing_commands": [],
                    "acceptance_criteria": ["tests green"],
                }
            )
        elif "coding swarm" in system:
            content = json.dumps(
                {
                    "task_id": "task-1",
                    "summary": "candidate patch",
                    "file_operations": [{"mode": "replace_block", "path": "app/auth.py", "old": "value = 'same'\n", "new": "value = 'same'\n"}],
                    "commands": [],
                    "skill_requests": [],
                    "notes": [],
                }
            )
        elif "testing swarm" in system:
            content = json.dumps({"summary": "tests ok", "commands": [], "expected_outputs": []})
        elif "debugging swarm" in system:
            content = json.dumps({"summary": "no repair", "root_cause": "none", "file_operations": [], "commands": [], "notes": []})
        else:
            content = json.dumps({"summary": "security ok", "issues": [], "recommended_commands": []})
        return {"content": content, "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, "model": model, "provider": "repair"}


class RewriteFallbackProvider:
    def validate_config(self):
        return True

    def get_available_models(self):
        return ["repair/reasoning", "repair/coding"]

    async def complete(self, model, messages, **kwargs):
        system = messages[0]["content"].lower()
        user = messages[-1]["content"]
        if "planning swarm" in system:
            content = json.dumps(
                {
                    "goal": "fix calculator bug",
                    "summary": "repair task",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "fix multiply",
                            "objective": "fix the multiply implementation",
                            "target_files": ["app/calculator.py", "tests/test_calculator.py"],
                            "deliverables": ["updated calculator"],
                            "commands": [{"command": "python -m pytest -q", "timeout": 60}],
                            "skill_requests": [],
                            "subtasks": [
                                {"id": "task-1-1", "title": "inspect code", "objective": "read files only"},
                                {"id": "task-1-2", "title": "apply fix", "objective": "update code"},
                            ],
                        }
                    ],
                    "testing_commands": [{"command": "python -m pytest -q", "timeout": 60}],
                    "acceptance_criteria": ["tests green"],
                }
            )
        elif "coding swarm rewrite fallback" in system:
            content = json.dumps(
                {
                    "task_id": "task-1",
                    "summary": "full file rewrite fallback",
                    "file_operations": [
                        {
                            "mode": "write",
                            "path": "app/calculator.py",
                            "content": "def multiply(a: int, b: int) -> int:\n    return a * b\n",
                        }
                    ],
                    "commands": [{"command": "python -m pytest -q", "timeout": 60}],
                    "skill_requests": [],
                    "notes": [],
                }
            )
        elif "coding swarm" in system:
            content = json.dumps(
                {
                    "task_id": "task-1",
                    "summary": "broken candidate",
                    "file_operations": [{"mode": "replace_block", "path": "app/calculator.py"}],
                    "commands": [{"command": "python -m pytest -q", "timeout": 60}],
                    "skill_requests": [],
                    "notes": [],
                }
            )
        elif "testing swarm" in system:
            content = json.dumps({"summary": "tests ok", "commands": [], "expected_outputs": []})
        elif "debugging swarm" in system:
            content = json.dumps({"summary": "no repair", "root_cause": "none", "file_operations": [], "commands": [], "notes": []})
        else:
            content = json.dumps({"summary": "security ok", "issues": [], "recommended_commands": []})
        return {"content": content, "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, "model": model, "provider": "repair"}


class NoopVsChangeProvider:
    def validate_config(self):
        return True

    def get_available_models(self):
        return ["repair/reasoning", "repair/coding"]

    async def complete(self, model, messages, **kwargs):
        system = messages[0]["content"].lower()
        user = messages[-1]["content"]
        if "planning swarm" in system:
            content = json.dumps(
                {
                    "goal": "fix module value",
                    "summary": "repair task",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "fix module value",
                            "objective": "fix the module value",
                            "target_files": ["pkg/module.py"],
                            "deliverables": ["updated module"],
                            "commands": [{"command": "python -c \"from pkg.module import VALUE; assert VALUE == 2\"", "timeout": 30}],
                            "skill_requests": [],
                        }
                    ],
                    "testing_commands": [],
                    "acceptance_criteria": ["value is updated"],
                }
            )
        elif "coding swarm" in system:
            if '"index": 1' in user:
                content = json.dumps(
                    {
                        "task_id": "task-1",
                        "summary": "noop candidate",
                        "file_operations": [],
                        "commands": [{"command": "python -c \"print('noop')\"", "timeout": 30}],
                        "skill_requests": [],
                        "notes": [],
                    }
                )
            else:
                content = json.dumps(
                    {
                        "task_id": "task-1",
                        "summary": "real fix candidate",
                        "file_operations": [{"mode": "write", "path": "pkg/module.py", "content": "VALUE = 2\n"}],
                        "commands": [{"command": "python -c \"from pkg.module import VALUE; assert VALUE == 2\"", "timeout": 30}],
                        "skill_requests": [],
                        "notes": [],
                    }
                )
        elif "testing swarm" in system:
            content = json.dumps({"summary": "tests ok", "commands": [], "expected_outputs": []})
        elif "debugging swarm" in system:
            content = json.dumps({"summary": "no repair", "root_cause": "none", "file_operations": [], "commands": [], "notes": []})
        else:
            content = json.dumps({"summary": "security ok", "issues": [], "recommended_commands": []})
        return {"content": content, "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, "model": model, "provider": "repair"}


class ValidationMergeProvider:
    def validate_config(self):
        return True

    def get_available_models(self):
        return ["repair/reasoning", "repair/coding"]

    async def complete(self, model, messages, **kwargs):
        system = messages[0]["content"].lower()
        if "planning swarm" in system:
            content = json.dumps(
                {
                    "goal": "fix multiply bug",
                    "summary": "generic repair plan",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "fix multiply bug",
                            "objective": "fix the multiply bug in the calculator implementation",
                            "target_files": ["app/calculator.py"],
                            "deliverables": ["updated calculator"],
                            "commands": [],
                            "skill_requests": [],
                        },
                        {
                            "id": "task-2",
                            "title": "validate calculator tests",
                            "objective": "run pytest to verify the fix",
                            "target_files": ["tests/test_calculator.py"],
                            "deliverables": ["test execution results"],
                            "commands": [{"command": "python -m pytest tests/test_calculator.py -q", "timeout": 60}],
                            "skill_requests": [],
                        },
                    ],
                    "testing_commands": [],
                    "acceptance_criteria": ["tests green"],
                }
            )
        elif "coding swarm" in system:
            content = json.dumps(
                {
                    "task_id": "task-1",
                    "summary": "generic fix candidate",
                    "file_operations": [
                        {
                            "mode": "write",
                            "path": "app/calculator.py",
                            "content": "def multiply(a: int, b: int) -> int:\n    return a * b\n",
                        }
                    ],
                    "commands": [],
                    "skill_requests": [],
                    "notes": [],
                }
            )
        elif "testing swarm" in system:
            content = json.dumps({"summary": "tests ok", "commands": [], "expected_outputs": []})
        elif "debugging swarm" in system:
            content = json.dumps({"summary": "no repair", "root_cause": "none", "file_operations": [], "commands": [], "notes": []})
        else:
            content = json.dumps({"summary": "security ok", "issues": [], "recommended_commands": []})
        return {"content": content, "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, "model": model, "provider": "repair"}


class BlockedVerificationProvider:
    def validate_config(self):
        return True

    def get_available_models(self):
        return ["repair/reasoning", "repair/coding"]

    async def complete(self, model, messages, **kwargs):
        system = messages[0]["content"].lower()
        if "planning swarm" in system:
            content = json.dumps(
                {
                    "goal": "create hello artifact",
                    "summary": "simple file task",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "create hello file",
                            "objective": "create hello.txt with the text hello",
                            "target_files": ["hello.txt"],
                            "deliverables": ["hello.txt"],
                            "commands": [],
                            "skill_requests": [],
                        }
                    ],
                    "testing_commands": [{"command": "type hello.txt", "timeout": 30}],
                    "acceptance_criteria": ["hello.txt exists", "hello.txt contains hello"],
                }
            )
        elif "coding swarm" in system:
            content = json.dumps(
                {
                    "task_id": "task-1",
                    "summary": "created file",
                    "file_operations": [{"mode": "write", "path": "hello.txt", "content": "hello"}],
                    "commands": [{"command": "type hello.txt", "timeout": 30}],
                    "skill_requests": [],
                    "notes": [],
                }
            )
        elif "testing swarm" in system:
            content = json.dumps({"summary": "verify file", "commands": [{"command": "type hello.txt", "timeout": 30}], "expected_outputs": ["hello"]})
        elif "debugging swarm" in system:
            content = json.dumps({"summary": "rewrite file", "root_cause": "policy blocked type command", "file_operations": [], "commands": [{"command": "type hello.txt", "timeout": 30}], "notes": []})
        else:
            content = json.dumps({"summary": "security ok", "issues": [], "recommended_commands": [{"command": "type hello.txt", "timeout": 30}]})
        return {"content": content, "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, "model": model, "provider": "repair"}


class GenericBackfillProvider:
    def validate_config(self):
        return True

    def get_available_models(self):
        return ["repair/reasoning", "repair/coding"]

    async def complete(self, model, messages, **kwargs):
        system = messages[0]["content"].lower()
        if "planning swarm" in system:
            content = json.dumps(
                {
                    "goal": "fix multiply bug",
                    "summary": "generic repair plan",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "fix multiply bug",
                            "objective": "repair the calculator bug from repo context",
                            "target_files": ["tests/test_calculator.py"],
                            "deliverables": ["bugfix"],
                            "commands": [{"command": "python -m pytest tests/test_calculator.py -q", "timeout": 60}],
                            "skill_requests": [],
                        }
                    ],
                    "testing_commands": [],
                    "acceptance_criteria": ["tests green"],
                }
            )
        elif "coding swarm" in system:
            content = json.dumps(
                {
                    "task_id": "task-1",
                    "summary": "repair candidate",
                    "file_operations": [
                        {
                            "mode": "write",
                            "path": "app/calculator.py",
                            "content": "def multiply(a: int, b: int) -> int:\n    return a * b\n",
                        }
                    ],
                    "commands": [{"command": "python -m pytest tests/test_calculator.py -q", "timeout": 60}],
                    "skill_requests": [],
                    "notes": [],
                }
            )
        elif "testing swarm" in system:
            content = json.dumps({"summary": "tests ok", "commands": [], "expected_outputs": []})
        elif "debugging swarm" in system:
            content = json.dumps({"summary": "no repair", "root_cause": "none", "file_operations": [], "commands": [], "notes": []})
        else:
            content = json.dumps({"summary": "security ok", "issues": [], "recommended_commands": []})
        return {"content": content, "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, "model": model, "provider": "repair"}


class FailingProvider:
    def validate_config(self):
        return True

    def get_available_models(self):
        return ["repair/reasoning", "repair/coding"]

    async def complete(self, model, messages, **kwargs):
        raise ValueError("simulated structured failure")


class DocsCommandProvider:
    def validate_config(self):
        return True

    def get_available_models(self):
        return ["repair/reasoning", "repair/coding"]

    async def complete(self, model, messages, **kwargs):
        system = messages[0]["content"].lower()
        if "planning swarm" in system:
            content = json.dumps(
                {
                    "goal": "write repo runbook",
                    "summary": "docs-only task",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "write runbook",
                            "objective": "create CHANGE_RUNBOOK.md for this mixed repo",
                            "target_files": ["CHANGE_RUNBOOK.md"],
                            "deliverables": ["CHANGE_RUNBOOK.md"],
                            "commands": [],
                            "skill_requests": [],
                        }
                    ],
                    "testing_commands": [],
                    "acceptance_criteria": ["runbook created"],
                }
            )
        elif "coding swarm" in system:
            content = json.dumps(
                {
                    "task_id": "task-1",
                    "summary": "write runbook",
                    "file_operations": [
                        {
                            "mode": "write",
                            "path": "CHANGE_RUNBOOK.md",
                            "content": "# Change Runbook\n\n- Python\n- TypeScript\n- Go\n",
                        }
                    ],
                    "commands": [{"command": "go test ./...", "timeout": 30}],
                    "skill_requests": [],
                    "notes": [],
                }
            )
        elif "debugging swarm" in system:
            content = json.dumps({"summary": "no repair", "root_cause": "none", "file_operations": [], "commands": [], "notes": []})
        else:
            content = json.dumps({"summary": "security ok", "issues": [], "recommended_commands": []})
        return {"content": content, "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, "model": model, "provider": "repair"}


class RetryStructuredProvider:
    def __init__(self):
        self.calls = 0

    def validate_config(self):
        return True

    def get_available_models(self):
        return ["repair/reasoning", "repair/coding"]

    async def complete(self, model, messages, **kwargs):
        self.calls += 1
        system = messages[0]["content"].lower()
        if "planning swarm" in system and self.calls == 1:
            return {"content": "not valid json", "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, "model": model, "provider": "repair"}
        if "planning swarm" in system:
            content = json.dumps(
                {
                    "goal": "fix multiply bug",
                    "summary": "retry succeeded",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "repair multiply",
                            "objective": "fix the multiply bug",
                            "target_files": ["app/calculator.py", "tests/test_calculator.py"],
                            "deliverables": ["updated calculator"],
                            "commands": [{"command": "python -m pytest tests/test_calculator.py -q", "timeout": 60}],
                            "skill_requests": [],
                        }
                    ],
                    "testing_commands": [],
                    "acceptance_criteria": ["tests green"],
                }
            )
        elif "coding swarm" in system:
            content = json.dumps(
                {
                    "task_id": "task-1",
                    "summary": "repair candidate",
                    "file_operations": [
                        {
                            "mode": "write",
                            "path": "app/calculator.py",
                            "content": "def multiply(a: int, b: int) -> int:\n    return a * b\n",
                        }
                    ],
                    "commands": [{"command": "python -m pytest tests/test_calculator.py -q", "timeout": 60}],
                    "skill_requests": [],
                    "notes": [],
                }
            )
        elif "debugging swarm" in system:
            content = json.dumps({"summary": "no repair", "root_cause": "none", "file_operations": [], "commands": [], "notes": []})
        else:
            content = json.dumps({"summary": "security ok", "issues": [], "recommended_commands": []})
        return {"content": content, "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, "model": model, "provider": "repair"}


class FastPathProvider:
    def validate_config(self):
        return True

    def get_available_models(self):
        return ["repair/reasoning", "repair/coding"]

    async def complete(self, model, messages, **kwargs):
        system = messages[0]["content"].lower()
        if "testing swarm" in system or "audit changes for" in messages[0]["content"].lower():
            raise AssertionError("fast-path run should not call testing or security swarms")
        if "planning swarm" in system:
            content = json.dumps(
                {
                    "goal": "fix multiply bug",
                    "summary": "fast localized repair",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "repair multiply",
                            "objective": "fix the multiply bug",
                            "target_files": ["app/calculator.py", "tests/test_calculator.py"],
                            "deliverables": ["updated calculator"],
                            "commands": [{"command": "python -m pytest tests/test_calculator.py -q", "timeout": 60}],
                            "skill_requests": [],
                        }
                    ],
                    "testing_commands": [],
                    "acceptance_criteria": ["tests green"],
                }
            )
        elif "coding swarm" in system:
            content = json.dumps(
                {
                    "task_id": "task-1",
                    "summary": "fast localized candidate",
                    "file_operations": [
                        {
                            "mode": "write",
                            "path": "app/calculator.py",
                            "content": "def multiply(a: int, b: int) -> int:\n    return a * b\n",
                        }
                    ],
                    "commands": [{"command": "python -m pytest tests/test_calculator.py -q", "timeout": 60}],
                    "skill_requests": [],
                    "notes": [],
                }
            )
        elif "debugging swarm" in system:
            content = json.dumps({"summary": "no repair", "root_cause": "none", "file_operations": [], "commands": [], "notes": []})
        else:
            content = json.dumps({"summary": "security ok", "issues": [], "recommended_commands": []})
        return {"content": content, "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, "model": model, "provider": "repair"}


def test_repo_context_symbols_and_impact_endpoints(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "core.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    (tmp_path / "pkg" / "feature.py").write_text("from pkg.core import alpha\n\ndef beta():\n    return alpha()\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_feature.py").write_text("from pkg.feature import beta\n", encoding="utf-8")

    app = create_app(tmp_path, provider=ScriptedEvalProvider())
    client = TestClient(app)

    context_response = client.get("/repo/context", params={"q": "fix feature bug", "limit": 6})
    symbols_response = client.get("/repo/symbols", params={"q": "alpha", "limit": 6})
    impact_response = client.get("/repo/impact", params=[("path", "pkg/core.py"), ("limit", "6")])

    assert context_response.status_code == 200
    assert any(item["path"] == "pkg/feature.py" for item in context_response.json()["focus"])
    assert symbols_response.status_code == 200
    assert any(item["name"] == "alpha" for item in symbols_response.json()["items"])
    assert impact_response.status_code == 200
    assert "tests/test_feature.py" in impact_response.json()["tests"]


def test_candidate_selection_records_ledger_and_rollback_bundle(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "auth.py").write_text("value = 'original'\n", encoding="utf-8")

    hive = HiveMind(RepairProvider(), tmp_path)

    async def run_case():
        await hive.initialize()
        try:
            return await hive.process_request("fix auth bug", mode="standard")
        finally:
            await hive.shutdown()

    result = asyncio.run(run_case())
    task = result["task_results"][0]
    assert task["sync"]["status"] == "committed"
    assert len(task["task_ledger"]["selection"]["candidates"]) >= 1
    assert task["rollback_bundle"]
    assert (tmp_path / "app" / "auth.py").read_text(encoding="utf-8") == "value = 'fixed'\n"


def test_candidate_patch_errors_are_recorded_without_crashing_session(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "auth.py").write_text("value = 'same'\n", encoding="utf-8")

    hive = HiveMind(ReplaceBlockFailureProvider(), tmp_path)

    async def run_case():
        await hive.initialize()
        try:
            return await hive.process_request("fix auth bug", mode="standard")
        finally:
            await hive.shutdown()

    result = asyncio.run(run_case())
    task = result["task_results"][0]
    assert result["status"] == "completed"
    assert task["sync"]["status"] == "kept_isolated_due_to_failures"
    assert "replace_block" in task["execution_error"]
    assert task["command_results"][0]["command"] == "candidate_execution"


def test_full_file_rewrite_fallback_repairs_simple_bugfix(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "calculator.py").write_text("def multiply(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calculator.py").write_text(
        "from app.calculator import multiply\n\n\ndef test_multiply():\n    assert multiply(3, 4) == 12\n",
        encoding="utf-8",
    )

    hive = HiveMind(RewriteFallbackProvider(), tmp_path)

    async def run_case():
        await hive.initialize()
        try:
            return await hive.process_request("fix calculator bug", mode="standard")
        finally:
            await hive.shutdown()

    result = asyncio.run(run_case())
    assert len(result["task_results"]) == 1
    task = result["task_results"][0]
    assert task["sync"]["status"] == "committed"
    assert task["normalization"]["fallback_used"] is True
    assert (tmp_path / "app" / "calculator.py").read_text(encoding="utf-8").strip().endswith("return a * b")


def test_noop_candidate_does_not_outrank_real_fix(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")

    hive = HiveMind(NoopVsChangeProvider(), tmp_path)

    async def run_case():
        await hive.initialize()
        try:
            return await hive.process_request("fix module value", mode="standard")
        finally:
            await hive.shutdown()

    result = asyncio.run(run_case())
    task = result["task_results"][0]
    assert task["sync"]["status"] == "committed"
    assert task["required_change"] is True
    assert task["target_hit_count"] >= 1
    assert (tmp_path / "pkg" / "module.py").read_text(encoding="utf-8") == "VALUE = 2\n"


def test_validation_only_tasks_are_merged_into_primary_fix(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "calculator.py").write_text("def multiply(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calculator.py").write_text(
        "from app.calculator import multiply\n\n\ndef test_multiply():\n    assert multiply(3, 4) == 12\n",
        encoding="utf-8",
    )

    hive = HiveMind(ValidationMergeProvider(), tmp_path)

    async def run_case():
        await hive.initialize()
        try:
            return await hive.process_request("Fix the multiply bug, run the relevant tests, and stop with evidence if confidence is too low.", mode="standard")
        finally:
            await hive.shutdown()

    result = asyncio.run(run_case())
    assert len(result["task_results"]) == 1
    task = result["task_results"][0]
    assert task["sync"]["status"] == "committed"
    assert any("pytest tests/test_calculator.py -q" in item.get("command", "") for item in task["command_results"])
    assert (tmp_path / "app" / "calculator.py").read_text(encoding="utf-8").strip().endswith("return a * b")


def test_blocked_verification_commands_are_normalized(tmp_path: Path):
    hive = HiveMind(BlockedVerificationProvider(), tmp_path)
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")

    async def run_case():
        await hive.initialize()
        try:
            return await hive._run_command_batch([{"command": "type hello.txt", "timeout": 30}], root=tmp_path)
        finally:
            await hive.shutdown()

    results, approvals = asyncio.run(run_case())
    assert not approvals
    assert results
    assert results[0]["normalized_from"] == "type hello.txt"
    assert results[0]["returncode"] == 0


def test_generic_prompt_target_backfill_accepts_fix_from_repo_context(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "calculator.py").write_text("def multiply(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calculator.py").write_text(
        "from app.calculator import multiply\n\n\ndef test_multiply():\n    assert multiply(3, 4) == 12\n",
        encoding="utf-8",
    )

    hive = HiveMind(GenericBackfillProvider(), tmp_path)

    async def run_case():
        await hive.initialize()
        try:
            return await hive.process_request("Fix the bug in this repo and run the relevant tests.", mode="standard")
        finally:
            await hive.shutdown()

    result = asyncio.run(run_case())
    task = result["task_results"][0]
    assert task["sync"]["status"] == "committed"
    assert "app/calculator.py" in task["task"]["target_files"]
    assert (tmp_path / "app" / "calculator.py").read_text(encoding="utf-8").strip().endswith("return a * b")


def test_migration_backfill_prefers_call_sites_over_api_definitions(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "legacy.py").write_text("def legacy_sum(values):\n    return sum(values)\n", encoding="utf-8")
    (tmp_path / "new_api.py").write_text("def sum_numbers(values):\n    return sum(values)\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text("from legacy import legacy_sum\n\n\ndef total(values):\n    return legacy_sum(values)\n", encoding="utf-8")
    (tmp_path / "tests" / "test_consumer.py").write_text(
        "from consumer import total\n\n\ndef test_total() -> None:\n    assert total([1, 2, 3]) == 6\n",
        encoding="utf-8",
    )
    hive = HiveMind(ScriptedEvalProvider(), tmp_path)
    repo_context = hive.repo_index.context_pack(
        "migrate this repo off legacy_sum to the new API, preserve behavior, and run the targeted validation",
        limit=8,
    )
    task = {
        "id": "task-1",
        "title": "migrate consumer",
        "objective": "migrate this repo off legacy_sum to the new API",
        "target_files": [],
    }

    backfilled = hive._backfill_task_targets(task, repo_context)

    assert "consumer.py" in backfilled["target_files"]
    assert "tests/test_consumer.py" in backfilled["target_files"]


def test_auto_validation_prefers_targeted_pytest_for_small_repairs(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "calculator.py").write_text("def multiply(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calculator.py").write_text(
        "from app.calculator import multiply\n\n\ndef test_multiply():\n    assert multiply(3, 4) == 12\n",
        encoding="utf-8",
    )
    hive = HiveMind(ScriptedEvalProvider(), tmp_path)
    route = TaskRoute(
        task_id="task-1",
        lane="repair",
        model="coding",
        isolation="git-worktree",
        test_strategy="full",
        repair_focus="root-cause",
        parallel_safe=True,
        cost_tier="balanced",
    )
    task = {"id": "task-1", "target_files": ["app/calculator.py", "tests/test_calculator.py"]}

    commands = hive._auto_validation_commands(tmp_path, route, task, ["app/calculator.py"])

    assert any(item["command"] == "pytest -q tests/test_calculator.py" for item in commands)
    assert not any(item["command"] == "pytest -q" for item in commands)


def test_candidate_model_hint_prefers_coding_for_refactor_edits(tmp_path: Path):
    hive = HiveMind(ScriptedEvalProvider(), tmp_path)
    route = TaskRoute(
        task_id="task-1",
        lane="refactor",
        model="reasoning",
        isolation="git-worktree",
        test_strategy="targeted",
        repair_focus="safe-structural",
        parallel_safe=True,
        cost_tier="high-confidence",
    )
    task = {"id": "task-1", "target_files": ["packages/shared/auth.py", "apps/api/service.py", "docs/auth.md"]}
    assert hive._candidate_model_hint(task, route) == "coding"


def test_localized_repairs_skip_model_testing_and_security_passes(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "calculator.py").write_text("def multiply(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calculator.py").write_text(
        "from app.calculator import multiply\n\n\ndef test_multiply():\n    assert multiply(3, 4) == 12\n",
        encoding="utf-8",
    )

    hive = HiveMind(FastPathProvider(), tmp_path)

    async def run_case():
        await hive.initialize()
        try:
            return await hive.process_request("Fix the multiply bug in this repo, run the relevant tests, and stop with evidence if confidence is too low.", mode="standard")
        finally:
            await hive.shutdown()

    result = asyncio.run(run_case())
    assert result["status"] == "completed"
    assert result["testing"]["source"] == "task-level-validation"
    assert result["security"]["model_findings"]["source"] == "static-and-heuristic"
    assert (tmp_path / "app" / "calculator.py").read_text(encoding="utf-8").strip().endswith("return a * b")


def test_api_returns_structured_failure_payload(tmp_path: Path):
    app = create_app(tmp_path, provider=FailingProvider())
    client = TestClient(app)

    response = client.post("/runs", json={"prompt": "fail intentionally"})

    assert response.status_code == 500
    payload = response.json()
    assert payload["detail"]["message"] == "VIKI run failed"
    assert payload["detail"]["error_type"] == "ValueError"


def test_docs_only_tasks_ignore_generated_runtime_commands(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "web").mkdir()
    (tmp_path / "go" / "cmd" / "server").mkdir(parents=True)
    (tmp_path / "src" / "main.py").write_text("def run() -> str:\n    return 'python-service'\n", encoding="utf-8")
    (tmp_path / "web" / "app.ts").write_text("export function boot(): string {\n  return 'web-app';\n}\n", encoding="utf-8")
    (tmp_path / "go" / "cmd" / "server" / "main.go").write_text(
        "package main\n\nimport \"fmt\"\n\nfunc main() {\n\tfmt.Println(\"server\")\n}\n",
        encoding="utf-8",
    )
    hive = HiveMind(DocsCommandProvider(), tmp_path)

    async def run_case():
        await hive.initialize()
        try:
            return await hive.process_request("Inspect this mixed repo and create CHANGE_RUNBOOK.md with validation commands.", mode="standard")
        finally:
            await hive.shutdown()

    result = asyncio.run(run_case())
    assert result["status"] == "completed"
    assert result["changed_files"] == ["CHANGE_RUNBOOK.md"]
    assert result["tasks"][0]["target_files"] == ["CHANGE_RUNBOOK.md"]
    assert all(item.get("command") != "go test ./..." for item in result["commands"])
    runbook = (tmp_path / "CHANGE_RUNBOOK.md").read_text(encoding="utf-8")
    assert "python -c" in runbook
    assert "npx tsc --noEmit web/app.ts" in runbook
    assert "go run go/cmd/server/main.go" in runbook


def test_missing_executable_returns_structured_command_result(tmp_path: Path, monkeypatch):
    executor = WorkspaceExecutor(tmp_path)

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("[WinError 2] missing binary")

    monkeypatch.setattr("viki.core.actions.subprocess.run", fake_run)
    result = executor.run_command("python -m pytest -q", root=tmp_path)
    assert result["returncode"] == 127
    assert result["runtime"] == "missing-executable"


def test_invalid_structured_response_retries_and_recovers(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "calculator.py").write_text("def multiply(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calculator.py").write_text(
        "from app.calculator import multiply\n\n\ndef test_multiply():\n    assert multiply(3, 4) == 12\n",
        encoding="utf-8",
    )
    provider = RetryStructuredProvider()
    hive = HiveMind(provider, tmp_path)

    async def run_case():
        await hive.initialize()
        try:
            return await hive.process_request("Fix the multiply bug in this repo, run the relevant tests, and stop with evidence if confidence is too low.", mode="standard")
        finally:
            await hive.shutdown()

    result = asyncio.run(run_case())
    assert result["status"] == "completed"
    assert provider.calls >= 2
    assert (tmp_path / "app" / "calculator.py").read_text(encoding="utf-8").strip().endswith("return a * b")


def test_messaging_commands_cover_sessions_patch_symbols_and_logs(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "core.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    app = create_app(tmp_path, provider=ScriptedEvalProvider())
    client = TestClient(app)

    run_response = client.post("/runs", json={"prompt": "create hello.txt with the text hello from benchmark"})
    assert run_response.status_code == 200
    session_id = run_response.json()["run"]["session_id"]
    server = app.state.viki_server

    sessions = asyncio.run(server._handle_integration_command("/sessions"))
    patch = asyncio.run(server._handle_integration_command(f"/patch {session_id}"))
    symbols = asyncio.run(server._handle_integration_command("/symbols alpha"))
    logs = asyncio.run(server._handle_integration_command(f"/logs {session_id}"))

    assert "Recent sessions:" in sessions
    assert "Patch bundle" in patch
    assert "alpha" in symbols
    assert "Latest command results" in logs or "No command logs available" in logs


def test_vscode_extension_contains_operational_commands(tmp_path: Path):
    VSCodeIntegrator(tmp_path).install_extension_scaffold()
    package_json = json.loads((tmp_path / ".viki-workspace" / "ide" / "vscode-extension" / "package.json").read_text(encoding="utf-8"))
    commands = {item["command"] for item in package_json["contributes"]["commands"]}
    assert "viki.submitTask" in commands
    assert "viki.symbolLookup" in commands
    assert "viki.previewDiff" in commands


def test_generate_stress_repos_creates_all_scenarios(tmp_path: Path):
    manifest = generate_stress_repos(tmp_path / "synthetic")
    assert set(manifest) == {
        "monorepo",
        "polyglot",
        "migration",
        "flaky",
        "bug_localization",
        "dependency_conflict",
        "large_test_matrix",
    }
    assert (Path(manifest["bug_localization"]) / "tests" / "test_calculator.py").exists()


def test_litellm_provider_accepts_dashscope_configuration():
    with patch.dict(
        os.environ,
        {
            "DASHSCOPE_API_KEY": "redacted",
            "OPENAI_API_BASE": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            "VIKI_CODING_MODEL": "openai/qwen3-coder-next",
        },
        clear=False,
    ):
        provider = LiteLLMProvider()
        if not provider._available:
            return
        assert provider.validate_config() is True
        assert "dashscope" in provider.available_backends()
        assert "openai/qwen3-coder-next" in provider.get_available_models()


def test_live_suite_runs_cli_from_primary_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target_repo = tmp_path / "target"
    target_repo.mkdir()
    suite = LiveExecutionSuite(workspace, tmp_path / "results")

    recorded: dict[str, object] = {}

    def fake_run(command, cwd, capture_output, text, timeout, env):
        recorded["command"] = command
        recorded["cwd"] = cwd

        class Completed:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return Completed()

    with patch("viki.evals.live_suite.subprocess.run", side_effect=fake_run):
        result = suite._prepare_workspace(target_repo)

    assert recorded["cwd"] == str(workspace)
    assert result["returncode"] == 0
    assert result["command"][3] == "up"
    assert str(target_repo) in result["command"]


def test_scripted_provider_rollout_updates_cli_and_docs():
    provider = ScriptedEvalProvider()

    async def run_case():
        return await provider.complete(
            "scripted/coding",
            [
                {"role": "system", "content": "You are VIKI coding swarm. Respond with JSON only."},
                {"role": "user", "content": "Roll out the new account normalization naming across this monorepo, preserve behavior, update the docs that still mention the old helper, and run the relevant tests."},
            ],
        )

    payload = json.loads(asyncio.run(run_case())["content"])
    changed_paths = {item["path"] for item in payload["file_operations"]}
    assert "apps/cli/commands.py" in changed_paths
    assert "docs/auth.md" in changed_paths


def test_natural_language_request_normalization_adds_local_execution_guidance(tmp_path: Path, monkeypatch):
    hive = HiveMind(ScriptedEvalProvider(), tmp_path)
    monkeypatch.setattr(hive, "_selected_provider_name", lambda: "ollama")

    normalized = hive._normalize_user_request("fix this bug and make the tests pass")

    assert "Execution guidance for VIKI" in normalized
    assert "smallest safe fix" in normalized
    assert "active model is local-first" in normalized
