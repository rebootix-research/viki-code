from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from .._log import structlog
from ..config import settings
from ..infrastructure.security import DockerSandbox, SecretBroker, SecurityScanner
from ..tools.ast_edits import ASTEditEngine
from ..tools.patches import PatchApplyError, PatchEngine

logger = structlog.get_logger()


class WorkspaceExecutor:
    def __init__(self, workspace_path: str | Path, security: SecurityScanner | None = None, sandbox: DockerSandbox | None = None):
        self.workspace = Path(workspace_path).resolve()
        self.security = security or SecurityScanner()
        self.sandbox = sandbox or DockerSandbox()
        self.patches = PatchEngine()
        self.ast_engine = ASTEditEngine()
        self.secrets = SecretBroker()

    def resolve_path(self, relative_path: str) -> Path:
        candidate = (self.workspace / relative_path).resolve()
        if self.workspace not in candidate.parents and candidate != self.workspace:
            raise ValueError(f"Path escapes workspace: {relative_path}")
        return candidate

    def validate_file_operation(self, operation: Dict[str, Any]) -> Dict[str, Any]:
        mode = operation.get("mode", "write")
        path = operation.get("path")
        if not path:
            raise ValueError("file operation missing path")
        if mode == "write" and "content" not in operation:
            raise ValueError("write operation missing content")
        if mode == "append" and "content" not in operation:
            raise ValueError("append operation missing content")
        if mode == "patch" and not operation.get("patch"):
            raise ValueError("patch operation missing patch text")
        if mode == "replace_block":
            if "old" not in operation or "new" not in operation:
                raise ValueError("replace_block missing old/new")
            if operation.get("old") == operation.get("new"):
                raise ValueError("replace_block old and new are identical")
        if mode == "ast_replace_function":
            if not operation.get("symbol"):
                raise ValueError("ast_replace_function missing symbol")
            if "content" not in operation:
                raise ValueError("ast_replace_function missing content")
        if mode == "json_merge" and not isinstance(operation.get("content"), dict):
            raise ValueError("json_merge content must be an object")
        return operation

    def apply_file_operations(self, operations: List[Dict[str, Any]]) -> List[str]:
        changed: List[str] = []
        for op in operations:
            self.validate_file_operation(op)
            mode = op.get("mode", "write")
            path = op.get("path")
            if not path:
                continue
            target = self.resolve_path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            if mode == "mkdir":
                target.mkdir(parents=True, exist_ok=True)
            elif mode == "delete":
                if target.exists():
                    target.unlink()
            elif mode == "append":
                with target.open("a", encoding="utf-8") as handle:
                    handle.write(op.get("content", ""))
            elif mode == "patch":
                original = target.read_text(encoding="utf-8") if target.exists() else ""
                updated = self.patches.apply_patch(original, op.get("patch", ""))
                self._write_checked(target, updated)
            elif mode == "replace_block":
                original = target.read_text(encoding="utf-8") if target.exists() else ""
                updated = self.patches.replace_block(original, op.get("old", ""), op.get("new", ""), int(op.get("count", 1)))
                self._write_checked(target, updated)
            elif mode == "ast_replace_function":
                original = target.read_text(encoding="utf-8") if target.exists() else ""
                updated = self.ast_engine.replace_function_source(original, op["symbol"], op["content"])
                self._write_checked(target, updated)
            elif mode == "json_merge":
                current = json.loads(target.read_text(encoding="utf-8") or "{}") if target.exists() else {}
                current.update(op.get("content", {}))
                self._write_checked(target, json.dumps(current, indent=2) + "\n")
            else:
                self._write_checked(target, op.get("content", ""))
            changed.append(target.relative_to(self.workspace).as_posix())
        return changed

    def _write_checked(self, target: Path, content: str) -> None:
        safe, violations = self.security.scan_code(content, str(target))
        if not safe and target.suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".sh"}:
            raise ValueError(f"Security violations for {target}: {violations}")
        target.write_text(content, encoding="utf-8")

    def _prepare_command(self, command: str, cwd: Path, env: Dict[str, str]) -> str:
        prepared = command.strip()
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(cwd) if not existing_pythonpath else str(cwd) + os.pathsep + existing_pythonpath
        if "--rootdir" in prepared:
            return prepared
        python_pytest = re.compile(r"^(python(?:[\d.]+)?(?:\.exe)?\s+-m\s+pytest)\b", re.IGNORECASE)
        bare_pytest = re.compile(r"^(pytest(?:\.exe)?)\b", re.IGNORECASE)
        if python_pytest.match(prepared):
            return python_pytest.sub(r"\1 --rootdir .", prepared, count=1)
        if bare_pytest.match(prepared):
            return bare_pytest.sub(r"\1 --rootdir .", prepared, count=1)
        return prepared

    def _normalize_interpreter_command(self, command: str) -> str:
        if os.name == "nt":
            return command
        try:
            tokens = shlex.split(command, posix=True)
        except ValueError:
            return command
        if not tokens:
            return command
        replacements = {
            "python": "python3",
            "pip": "pip3",
        }
        replacement = replacements.get(tokens[0])
        if replacement and shutil.which(tokens[0]) is None and shutil.which(replacement):
            tokens[0] = replacement
            return shlex.join(tokens)
        return command

    def run_command(self, command: str, timeout: int = 120, root: str | Path | None = None, secret_names: List[str] | None = None, network_enabled: bool | None = None, labels: Dict[str, str] | None = None) -> Dict[str, Any]:
        allowed, reason = self.security.validate_command(command)
        if not allowed:
            return {"returncode": 126, "output": "", "error": reason, "command": command, "runtime": "blocked"}
        cwd = Path(root).resolve() if root else self.workspace
        env = os.environ.copy()
        env.update(self.secrets.export(secret_names or []))
        prepared_command = self._prepare_command(command, cwd, env)
        prepared_command = self._normalize_interpreter_command(prepared_command)

        sandbox_network = settings.sandbox_network_enabled if network_enabled is None else network_enabled

        if settings.sandbox_enabled and self.sandbox.available:
            try:
                result = self.sandbox.run_command(
                    str(cwd),
                    prepared_command,
                    timeout=timeout,
                    network_enabled=sandbox_network,
                    environment=self.secrets.export(secret_names or []),
                    labels=labels,
                )
            except Exception as exc:
                logger.warning(
                    "sandbox command failed, falling back to local execution",
                    command=prepared_command,
                    cwd=str(cwd),
                    error=str(exc),
                )
                if hasattr(self.sandbox, "client"):
                    try:
                        self.sandbox.client = None
                    except Exception:
                        pass
            else:
                return {
                    "returncode": result.get("returncode", 1),
                    "output": self.security.redact_text(str(result.get("output", ""))),
                    "error": self.security.redact_text(str(result.get("error", ""))),
                    "command": command,
                    "effective_command": prepared_command,
                    "cwd": str(cwd),
                    "runtime": result.get("runtime", "docker"),
                    "sandboxed": True,
                    "sandbox_profile": result.get("profile", {}),
                }

        if os.name == "nt":
            tokens: str | list[str] = prepared_command
        else:
            try:
                tokens = shlex.split(prepared_command, posix=True)
            except ValueError as exc:
                return {
                    "returncode": 126,
                    "output": "",
                    "error": f"malformed shell command: {exc}",
                    "command": command,
                    "effective_command": prepared_command,
                    "cwd": str(cwd),
                    "runtime": "blocked",
                    "sandboxed": False,
                }
        try:
            completed = subprocess.run(
                tokens,
                cwd=cwd,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        except FileNotFoundError as exc:
            return {
                "returncode": 127,
                "output": "",
                "error": self.security.redact_text(str(exc)),
                "command": command,
                "effective_command": prepared_command,
                "cwd": str(cwd),
                "runtime": "missing-executable",
                "sandboxed": False,
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "returncode": 124,
                "output": self.security.redact_text(str(exc.stdout or "")),
                "error": self.security.redact_text(str(exc.stderr or "command timed out")),
                "command": command,
                "effective_command": prepared_command,
                "cwd": str(cwd),
                "runtime": "local",
                "sandboxed": False,
            }
        return {
            "returncode": completed.returncode,
            "output": self.security.redact_text(completed.stdout),
            "error": self.security.redact_text(completed.stderr),
            "command": command,
            "effective_command": prepared_command,
            "cwd": str(cwd),
            "runtime": "local",
            "sandboxed": False,
        }

    def search_files(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        query_lower = query.lower()
        for path in self.workspace.rglob("*"):
            if not path.is_file():
                continue
            if any(part in {".git", ".viki-workspace", "node_modules", "__pycache__"} for part in path.parts):
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if query_lower in content.lower() or query_lower in str(path).lower():
                results.append({"path": str(path.relative_to(self.workspace)), "preview": content[:400]})
            if len(results) >= limit:
                break
        return results
