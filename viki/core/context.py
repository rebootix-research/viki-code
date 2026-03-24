from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List


class ContextCompressor:
    def __init__(self, max_chars: int = 20000):
        self.max_chars = max_chars

    def compress(self, context: Dict[str, Any]) -> Dict[str, Any]:
        compressed = dict(context)
        all_paths = context.get("existing_files", [])
        compressed["existing_files"] = self._compact_paths(all_paths, 150)
        compressed["recent_memories"] = self._trim_list(context.get("recent_memories", []), 12)
        compressed["recent_failures"] = self._trim_list(context.get("recent_failures", []), 8)
        compressed["workspace_summary"] = self._workspace_summary(all_paths)
        compressed["repo_facts"] = self._repo_facts(all_paths)
        compressed["intent_summary"] = self._intent_summary(context)
        while len(str(compressed)) > self.max_chars:
            files = compressed.get("existing_files", [])
            if len(files) > 20:
                compressed["existing_files"] = files[:-10]
                continue
            memories = compressed.get("recent_memories", [])
            if memories:
                compressed["recent_memories"] = memories[:-1]
                continue
            failures = compressed.get("recent_failures", [])
            if failures:
                compressed["recent_failures"] = failures[:-1]
                continue
            break
        return compressed

    def _trim_list(self, items: Iterable[Any], limit: int) -> List[Any]:
        values = list(items)
        return values[-limit:]

    def _compact_paths(self, paths: Iterable[str], limit: int) -> List[str]:
        sorted_paths = sorted(set(str(p) for p in paths))
        if len(sorted_paths) <= limit:
            return sorted_paths
        head = sorted_paths[: limit // 2]
        tail = sorted_paths[-(limit // 2) :]
        return head + [f"... {len(sorted_paths) - len(head) - len(tail)} more files ..."] + tail

    def _workspace_summary(self, paths: Iterable[str]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in paths:
            suffix = Path(item).suffix or "[no_ext]"
            counts[suffix] = counts.get(suffix, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:20])

    def _repo_facts(self, paths: Iterable[str]) -> Dict[str, Any]:
        paths_list = [str(p) for p in paths]
        top_dirs: Dict[str, int] = {}
        for item in paths_list:
            top = Path(item).parts[0] if Path(item).parts else "."
            top_dirs[top] = top_dirs.get(top, 0) + 1
        return {
            "file_count": len(paths_list),
            "top_directories": dict(sorted(top_dirs.items(), key=lambda kv: (-kv[1], kv[0]))[:12]),
            "has_tests": any("test" in item.lower() for item in paths_list),
            "has_ci": any(item.startswith(".github/") or "workflow" in item.lower() for item in paths_list),
        }

    def _intent_summary(self, context: Dict[str, Any]) -> Dict[str, Any]:
        request = str(context.get("request", ""))
        lowered = request.lower()
        constraints = []
        for token in ["without", "do not", "strict", "safe", "fast", "cheap", "minimal", "full"]:
            if token in lowered:
                constraints.append(token)
        intent = "implementation"
        if any(word in lowered for word in ["fix", "repair", "failing", "bug"]):
            intent = "repair"
        elif any(word in lowered for word in ["refactor", "migrate", "rename"]):
            intent = "structural-change"
        elif any(word in lowered for word in ["summarize", "inspect", "review", "analyze", "understand"]):
            intent = "analysis"
        elif any(word in lowered for word in ["continue", "resume", "pick up where we left off"]):
            intent = "continuation"
        elif any(word in lowered for word in ["test", "coverage", "ci"]):
            intent = "testing"
        return {
            "intent": intent,
            "constraints": constraints,
            "mode": context.get("mode", "standard"),
        }
