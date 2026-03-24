from __future__ import annotations

from viki.ollama_support import choose_best_ollama_model, parse_ollama_list


def test_parse_ollama_list_reads_model_names():
    output = """
NAME                  ID              SIZE      MODIFIED
qwen2.5-coder:7b      abc123          4.7 GB    2 days ago
llama3.2:3b           def456          2.0 GB    5 days ago
""".strip()

    assert parse_ollama_list(output) == ["qwen2.5-coder:7b", "llama3.2:3b"]


def test_choose_best_ollama_model_prefers_coding_capable_model():
    selected = choose_best_ollama_model(
        [
            "llama3.2:3b",
            "deepseek-r1:8b",
            "qwen2.5-coder:7b",
            "mistral:7b",
        ]
    )

    assert selected == "qwen2.5-coder:7b"
