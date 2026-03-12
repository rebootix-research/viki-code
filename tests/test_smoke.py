from __future__ import annotations

import asyncio
import json
from pathlib import Path

from viki.core.actions import WorkspaceExecutor
from viki.core.hive import HiveMind
from viki.infrastructure.database import DatabaseManager
from viki.skills.factory import AutoSkillFactory
from viki.skills.registry import SkillRegistry


class FakeProvider:
    def validate_config(self):
        return True

    def get_available_models(self):
        return ["fake/reasoning", "fake/coding"]

    async def complete(self, model, messages, **kwargs):
        system = messages[0]["content"].lower()
        if "planning swarm" in system:
            content = '''{
              "goal": "create a hello file",
              "summary": "single task plan",
              "tasks": [
                {
                  "id": "task-1",
                  "title": "write hello",
                  "objective": "write a hello.txt file",
                  "target_files": ["hello.txt"],
                  "deliverables": ["hello.txt"],
                  "commands": [],
                  "skill_requests": []
                }
              ],
              "testing_commands": [],
              "acceptance_criteria": ["hello.txt exists"]
            }'''
        elif "coding swarm" in system:
            content = '''{
              "task_id": "task-1",
              "summary": "created file",
              "file_operations": [
                {"mode": "write", "path": "hello.txt", "content": "hello from viki\\n"}
              ],
              "commands": [],
              "skill_requests": [],
              "notes": []
            }'''
        elif "testing swarm" in system:
            content = '''{
              "summary": "no-op tests",
              "commands": [{"command": "python -c \\\"print('tests ok')\\\"", "timeout": 30}],
              "expected_outputs": ["tests ok"]
            }'''
        elif "debugging swarm" in system:
            content = '''{
              "summary": "no repair needed",
              "root_cause": "none",
              "file_operations": [],
              "commands": [],
              "notes": []
            }'''
        else:
            content = '''{
              "summary": "security ok",
              "issues": [],
              "recommended_commands": []
            }'''
        return {
            "content": content,
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "model": model or "fake",
            "provider": "fake",
        }


def test_hivemind_smoke(tmp_path: Path):
    (tmp_path / ".viki-workspace").mkdir()

    async def run_test():
        hive = HiveMind(FakeProvider(), str(tmp_path))
        await hive.initialize()
        result = await hive.process_request("create hello file")
        assert result["status"].startswith("completed")
        assert (tmp_path / "hello.txt").read_text() == "hello from viki\n"
        assert "hello.txt" in result["changed_files"]
        assert result["pending_approvals"] == []

    asyncio.run(run_test())


def test_patch_and_block_edit(tmp_path: Path):
    target = tmp_path / "example.py"
    target.write_text("def alpha():\n    return 1\n", encoding="utf-8")
    executor = WorkspaceExecutor(tmp_path)
    changed = executor.apply_file_operations([
        {
            "mode": "replace_block",
            "path": "example.py",
            "old": "return 1",
            "new": "return 2",
        }
    ])
    assert changed == ["example.py"]
    assert "return 2" in target.read_text(encoding="utf-8")


def test_run_command_forces_pytest_rootdir_in_nested_workspace(tmp_path: Path):
    outer = tmp_path / "outer"
    candidate = outer / ".viki-workspace" / "runs" / "candidate"
    (candidate / "app").mkdir(parents=True)
    (candidate / "tests").mkdir(parents=True)
    (outer / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = \"-q\"\ntestpaths = [\"tests\"]\n",
        encoding="utf-8",
    )
    (candidate / "app" / "calculator.py").write_text(
        "def multiply(a: int, b: int) -> int:\n    return a * b\n",
        encoding="utf-8",
    )
    (candidate / "tests" / "test_calculator.py").write_text(
        "from app.calculator import multiply\n\n\ndef test_multiply():\n    assert multiply(3, 4) == 12\n",
        encoding="utf-8",
    )
    executor = WorkspaceExecutor(candidate)
    result = executor.run_command("python -m pytest -q", root=candidate, timeout=60)
    assert result["returncode"] == 0
    assert "--rootdir ." in result["effective_command"]


def test_prepare_command_falls_back_to_python3_when_python_missing(tmp_path: Path, monkeypatch):
    executor = WorkspaceExecutor(tmp_path)
    monkeypatch.setattr("viki.core.actions.os.name", "posix", raising=False)

    def fake_which(name: str):
        if name == "python":
            return None
        if name == "python3":
            return "/usr/bin/python3"
        return None

    monkeypatch.setattr("viki.core.actions.shutil.which", fake_which)
    prepared = executor._normalize_interpreter_command("python -m pytest --rootdir . tests/test_calculator.py -q")
    assert prepared.startswith("python3 -m pytest")


def test_run_command_falls_back_to_local_when_sandbox_execution_breaks(tmp_path: Path, monkeypatch):
    class BrokenSandbox:
        available = True

        def run_command(self, *args, **kwargs):
            raise RuntimeError("sandbox image missing")

    executor = WorkspaceExecutor(tmp_path, sandbox=BrokenSandbox())

    class Completed:
        returncode = 0
        stdout = "local ok\n"
        stderr = ""

    monkeypatch.setattr("viki.core.actions.settings.sandbox_enabled", True)
    monkeypatch.setattr("viki.core.actions.subprocess.run", lambda *args, **kwargs: Completed())

    result = executor.run_command("python -m pytest -q", root=tmp_path)

    assert result["returncode"] == 0
    assert result["runtime"] == "local"
    assert result["sandboxed"] is False
    assert "--rootdir ." in result["effective_command"]


def test_skill_factory_manifest_and_registry(tmp_path: Path):
    factory = AutoSkillFactory(str(tmp_path), provider=None)

    async def run_test():
        result = await factory.create_skill("Create a fallback skill", preferred_name="fallback_skill")
        assert Path(result["path"]).exists()
        manifest_path = Path(result["manifest"])
        assert manifest_path.exists()
        registry = SkillRegistry(tmp_path)
        assert registry.has("fallback_skill")

    asyncio.run(run_test())


def test_database_approval_flow(tmp_path: Path):
    db = DatabaseManager(str(tmp_path / ".viki-workspace" / "viki.db"))

    async def run_test():
        await db.initialize()
        approval_id = await db.create_approval("session-1", "command", "git push", "policy", 70, {"command": "git push"})
        pending = await db.list_approvals(status="pending")
        assert pending and pending[0]["id"] == approval_id
        await db.resolve_approval(approval_id, status="approved", reviewer="tester")
        approved = await db.list_approvals(status="approved")
        assert approved and approved[0]["id"] == approval_id

    asyncio.run(run_test())
