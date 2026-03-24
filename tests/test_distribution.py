from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from urllib.error import HTTPError

from typer.testing import CliRunner

from viki import __version__
from viki.cli import app
from viki.ollama_support import OllamaRuntimeStatus


runner = CliRunner()


def test_up_dry_run_prepares_workspace_and_env(tmp_path: Path):
    result = runner.invoke(app, ["up", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".viki-workspace").exists()
    assert (tmp_path / ".env").exists()
    assert "Dry run complete" in result.output


def test_bootstrap_project_root_detects_repo(tmp_path: Path):
    (tmp_path / "README.md").write_text("readme", encoding="utf-8")
    (tmp_path / "setup.py").write_text("setup", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[build-system]\nrequires=[]\n", encoding="utf-8")
    nested = tmp_path / "nested" / "path"
    nested.mkdir(parents=True)

    spec = importlib.util.spec_from_file_location("viki_bootstrap", Path(__file__).resolve().parents[1] / "scripts" / "bootstrap.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    detected = module.project_root(nested)
    assert detected == tmp_path.resolve()


def test_release_closure_post_run_returns_structured_http_error_payload(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "viki_release_closure_live",
        Path(__file__).resolve().parents[1] / "scripts" / "run_release_closure_live.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    error_body = json.dumps({"detail": {"message": "VIKI run failed", "error_type": "RuntimeError"}}).encode("utf-8")

    def fake_urlopen(req, timeout=0):  # pragma: no cover - monkeypatched behavior
        raise HTTPError(req.full_url, 500, "Internal Server Error", hdrs=None, fp=io.BytesIO(error_body))

    monkeypatch.setattr(module.urlrequest, "urlopen", fake_urlopen)

    status, payload = module.post_run("http://127.0.0.1:9999", "repair bug", "C:/repo")
    assert status == 500
    assert payload["detail"]["message"] == "VIKI run failed"


def test_version_command_prints_package_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0, result.output
    assert __version__ in result.output


def test_isolation_validator_forwards_live_provider_env():
    spec = importlib.util.spec_from_file_location(
        "viki_validate_isolation",
        Path(__file__).resolve().parents[1] / "scripts" / "validate_isolation.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    env = {
        "DASHSCOPE_API_KEY": "redacted",
        "OPENAI_API_BASE": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "VIKI_CODING_MODEL": "openai/qwen3-coder-next",
    }

    forwarded = module._forward_wsl_env(env)

    assert "WSLENV" in forwarded
    assert "DASHSCOPE_API_KEY" in forwarded["WSLENV"]
    assert "OPENAI_API_BASE" in forwarded["WSLENV"]
    assert "VIKI_CODING_MODEL" in forwarded["WSLENV"]


def test_isolation_validator_accepts_user_site_bootstrap_fallback():
    spec = importlib.util.spec_from_file_location(
        "viki_validate_isolation",
        Path(__file__).resolve().parents[1] / "scripts" / "validate_isolation.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    commands = [
        {"returncode": 0},  # create temp root
        {"returncode": 1},  # venv failure
        {"returncode": 0},  # get-pip download
        {"returncode": 0},  # bootstrap pip
        {"returncode": 0},  # install wheel + pytest
        {"returncode": 0},  # copy fixture
        {"returncode": 0},  # version
        {"returncode": 0},  # up
        {"returncode": 0},  # live task
        {"returncode": 0},  # pytest
    ]

    assert module._is_successful_run(commands, "user-site-bootstrap", 9) is True


def test_github_clone_validator_detects_dashscope_provider():
    spec = importlib.util.spec_from_file_location(
        "viki_validate_github_clone_live",
        Path(__file__).resolve().parents[1] / "scripts" / "validate_github_clone_live.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    detected = module.detect_live_provider(
        {
            "DASHSCOPE_API_KEY": "redacted",
            "VIKI_PROVIDER": "dashscope",
            "VIKI_CODING_MODEL": "openai/qwen3-coder-next",
        }
    )

    assert detected["provider"] == "dashscope"
    assert "DASHSCOPE_API_KEY" in detected["forwarded_keys"]


def test_github_clone_validator_isolates_selected_provider_env():
    spec = importlib.util.spec_from_file_location(
        "viki_validate_github_clone_live",
        Path(__file__).resolve().parents[1] / "scripts" / "validate_github_clone_live.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    isolated = module.isolate_provider_env(
        {
            "DASHSCOPE_API_KEY": "redacted",
            "OPENAI_API_KEY": "should-not-pass-through",
            "PATH": "keep-me",
        },
        {"provider": "dashscope", "forwarded_keys": ["DASHSCOPE_API_KEY"]},
    )

    assert isolated["DASHSCOPE_API_KEY"] == "redacted"
    assert "OPENAI_API_KEY" not in isolated
    assert isolated["VIKI_PROVIDER"] == "dashscope"


def test_onboarding_clone_validator_detects_nvidia_provider():
    spec = importlib.util.spec_from_file_location(
        "viki_validate_onboarding_clone_live",
        Path(__file__).resolve().parents[1] / "scripts" / "validate_onboarding_clone_live.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    detected = module.detect_live_provider(
        {
            "OPENAI_API_KEY": "redacted",
            "OPENAI_API_BASE": "https://integrate.api.nvidia.com/v1",
        }
    )

    assert detected["provider"] == "nvidia"


def test_onboarding_clone_validator_builds_nvidia_setup_input():
    spec = importlib.util.spec_from_file_location(
        "viki_validate_onboarding_clone_live",
        Path(__file__).resolve().parents[1] / "scripts" / "validate_onboarding_clone_live.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    setup_input = module.setup_wizard_input("nvidia")

    assert setup_input.startswith("6\n1\n")


def test_onboarding_clone_validator_isolates_nvidia_without_openai_fallback():
    spec = importlib.util.spec_from_file_location(
        "viki_validate_onboarding_clone_live",
        Path(__file__).resolve().parents[1] / "scripts" / "validate_onboarding_clone_live.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    isolated = module.isolate_provider_env(
        {
            "OPENAI_API_KEY": "redacted",
            "OPENAI_API_BASE": "https://integrate.api.nvidia.com/v1",
            "PATH": "keep-me",
        },
        {
            "provider": "nvidia",
            "forwarded_keys": ["OPENAI_API_KEY", "OPENAI_API_BASE"],
        },
    )

    assert isolated["NVIDIA_API_KEY"] == "redacted"
    assert isolated["NVIDIA_API_BASE"] == "https://integrate.api.nvidia.com/v1"
    assert "OPENAI_API_KEY" not in isolated
    assert isolated["VIKI_PROVIDER"] == "nvidia"


def test_github_clone_validator_remove_tree_handles_readonly_file(tmp_path: Path):
    spec = importlib.util.spec_from_file_location(
        "viki_validate_github_clone_live",
        Path(__file__).resolve().parents[1] / "scripts" / "validate_github_clone_live.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    target = tmp_path / "readonly"
    target.mkdir()
    file_path = target / "sample.txt"
    file_path.write_text("value", encoding="utf-8")
    file_path.chmod(0o444)

    module.remove_tree(target)

    assert not target.exists()


def test_connected_product_validator_prefers_dashscope_when_available(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "viki_validate_connected_product_clone_live",
        Path(__file__).resolve().parents[1] / "scripts" / "validate_connected_product_clone_live.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module,
        "get_ollama_runtime_status",
        lambda allow_pull=False: OllamaRuntimeStatus(
            cli_available=False,
            reachable=False,
            base_url="http://127.0.0.1:11434",
            models=(),
            selected_model=None,
            recommended_model="qwen2.5-coder:7b",
            error="missing",
        ),
    )

    detected = module.detect_live_provider(
        {
            "DASHSCOPE_API_KEY": "redacted",
            "DASHSCOPE_API_BASE": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            "OPENAI_API_KEY": "should-not-win",
        }
    )

    assert detected["provider"] == "dashscope"
    assert "DASHSCOPE_API_KEY" in detected["forwarded_keys"]


def test_connected_product_validator_prefers_ollama_when_local_runtime_is_ready(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "viki_validate_connected_product_clone_live",
        Path(__file__).resolve().parents[1] / "scripts" / "validate_connected_product_clone_live.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module,
        "get_ollama_runtime_status",
        lambda allow_pull=False: OllamaRuntimeStatus(
            cli_available=True,
            reachable=True,
            base_url="http://127.0.0.1:11434",
            models=("qwen2.5-coder:7b",),
            selected_model="qwen2.5-coder:7b",
            recommended_model="qwen2.5-coder:7b",
        ),
    )

    detected = module.detect_live_provider({})

    assert detected["provider"] == "ollama"
    assert detected["ollama_model"] == "qwen2.5-coder:7b"


def test_connected_product_validator_scrubs_unforwarded_provider_secrets():
    spec = importlib.util.spec_from_file_location(
        "viki_validate_connected_product_clone_live",
        Path(__file__).resolve().parents[1] / "scripts" / "validate_connected_product_clone_live.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    isolated = module.isolate_provider_env(
        {
            "DASHSCOPE_API_KEY": "redacted",
            "OPENAI_API_KEY": "remove-me",
            "PATH": "keep-me",
        },
        {"provider": "dashscope", "forwarded_keys": ["DASHSCOPE_API_KEY"]},
    )

    assert isolated["DASHSCOPE_API_KEY"] == "redacted"
    assert "OPENAI_API_KEY" not in isolated
    assert isolated["VIKI_PROVIDER"] == "dashscope"


def test_connected_product_validator_extracts_provider_failures():
    spec = importlib.util.spec_from_file_location(
        "viki_validate_connected_product_clone_live",
        Path(__file__).resolve().parents[1] / "scripts" / "validate_connected_product_clone_live.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    error = module.extract_provider_failure_text(
        {
            "stdout": "[ERROR] VIKI run failed: All provider attempts failed. dashscope:openai/qwen3.5-plus -> Incorrect API key provided",
            "stderr": "",
        }
    )

    assert error is not None
    assert "All provider attempts failed." in error


def test_bootstrap_retries_with_system_site_packages_and_no_deps(monkeypatch, tmp_path: Path):
    spec = importlib.util.spec_from_file_location(
        "viki_bootstrap",
        Path(__file__).resolve().parents[1] / "scripts" / "bootstrap.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    from viki.platforms import PlatformSupport

    root = tmp_path / "repo"
    root.mkdir()
    install_attempts: list[tuple[bool, bool]] = []
    create_calls: list[bool] = []
    run_commands: list[list[str]] = []

    def fake_create_venv(root_path: Path, target: Path, *, use_system_site_packages: bool = False):
        create_calls.append(use_system_site_packages)
        scripts_dir = target / "Scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        (scripts_dir / "python.exe").write_text("", encoding="utf-8")

    def fake_upgrade(root_path: Path, python_bin: Path):
        return None

    def fake_install(root_path: Path, python_bin: Path, *, install_dev: bool, update: bool, no_deps: bool = False):
        install_attempts.append((update, no_deps))
        if len(install_attempts) < 3:
            raise module.subprocess.CalledProcessError(returncode=1, cmd=["pip", "install"])

    class DummyProfile:
        os_name = "windows"
        launcher_hint = "viki"

    monkeypatch.setattr(module, "create_venv", fake_create_venv)
    monkeypatch.setattr(module, "upgrade_packaging_tools", fake_upgrade)
    monkeypatch.setattr(module, "install_project", fake_install)
    monkeypatch.setattr(PlatformSupport, "current", staticmethod(lambda: DummyProfile()))
    monkeypatch.setattr(PlatformSupport, "venv_python", staticmethod(lambda target, profile: target / "Scripts" / "python.exe"))
    monkeypatch.setattr(PlatformSupport, "write_local_launchers", staticmethod(lambda root_path, python_bin: []))
    monkeypatch.setattr(PlatformSupport, "write_user_launchers", staticmethod(lambda python_bin, profile: []))
    monkeypatch.setattr(module, "run", lambda cmd, cwd: run_commands.append(cmd))

    module.bootstrap(root=root, install_dev=False, force_env=False, run_server=False, host="127.0.0.1", port="8787", update=False)

    assert create_calls == [False, True]
    assert install_attempts == [(False, False), (False, False), (False, True)]
    assert any("viki.cli" in " ".join(command) for command in run_commands)
