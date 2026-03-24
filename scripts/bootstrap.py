from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT_MARKERS = ("pyproject.toml", "setup.py", "README.md")


def project_root(start: Path) -> Path:
    candidate = start.resolve()
    if candidate.is_file():
        candidate = candidate.parent
    for current in [candidate, *candidate.parents]:
        if all((current / marker).exists() for marker in ROOT_MARKERS):
            return current
    raise SystemExit("Unable to locate the VIKI project root.")


def run(cmd: list[str], cwd: Path) -> None:
    print("[viki-bootstrap]", " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd), check=True)


def create_venv(root: Path, venv_dir: Path, *, use_system_site_packages: bool = False) -> None:
    command = [sys.executable, "-m", "venv"]
    if use_system_site_packages:
        command.append("--system-site-packages")
    command.append(str(venv_dir))
    run(command, cwd=root)


def upgrade_packaging_tools(root: Path, python_bin: Path) -> None:
    run([str(python_bin), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], cwd=root)


def install_project(root: Path, python_bin: Path, *, install_dev: bool, update: bool, no_deps: bool = False) -> None:
    extras = "[dev]" if install_dev else ""
    command = [str(python_bin), "-m", "pip", "install"]
    if update:
        command.append("--upgrade")
    if no_deps:
        command.append("--no-deps")
    command.append(f".{extras}")
    run(command, cwd=root)


def bootstrap(root: Path, install_dev: bool, force_env: bool, run_server: bool, host: str, port: int, update: bool = False) -> None:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from viki.platforms import PlatformSupport

    profile = PlatformSupport.current()
    venv_dir = root / ".venv"
    python_bin = Path(str(PlatformSupport.venv_python(venv_dir, profile)))

    if not python_bin.exists():
        create_venv(root, venv_dir)

    upgrade_packaging_tools(root, python_bin)

    try:
        install_project(root, python_bin, install_dev=install_dev, update=update)
    except subprocess.CalledProcessError:
        print("[viki-bootstrap] dependency resolution failed; retrying with shared-runtime fallback")
        shutil.rmtree(venv_dir, ignore_errors=True)
        create_venv(root, venv_dir, use_system_site_packages=True)
        python_bin = Path(str(PlatformSupport.venv_python(venv_dir, profile)))
        upgrade_packaging_tools(root, python_bin)
        try:
            install_project(root, python_bin, install_dev=install_dev, update=update)
        except subprocess.CalledProcessError:
            print("[viki-bootstrap] provider/runtime packages appear to exist on the host interpreter; retrying without dependency resolution")
            install_project(root, python_bin, install_dev=install_dev, update=update, no_deps=True)

    init_cmd = [str(python_bin), "-m", "viki.cli", "up", str(root), "--dry-run"]
    if force_env:
        init_cmd.append("--force-env")
    run(init_cmd, cwd=root)

    launchers = PlatformSupport.write_local_launchers(root, python_bin)
    user_launchers = PlatformSupport.write_user_launchers(python_bin, profile)
    print("[viki-bootstrap] local launchers:")
    for launcher in launchers:
        print("  -", launcher)
    print("[viki-bootstrap] user launchers:")
    for launcher in user_launchers:
        print("  -", launcher)

    if run_server:
        run([str(python_bin), "-m", "viki.cli"], cwd=root)
        return

    launch_hint = "viki"
    print("[viki-bootstrap] ready")
    print("[viki-bootstrap] platform:", profile.os_name)
    print("[viki-bootstrap] launch:", launch_hint)
    print("[viki-bootstrap] shortcut:", profile.launcher_hint)
    print("[viki-bootstrap] first run: launch `viki` for the guided setup, or use the local launcher if your shell does not expose the user Scripts/bin directory yet.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bootstrap VIKI from a repo checkout or extracted zip.")
    parser.add_argument("--path", default=".", help="Path inside the VIKI repo or extracted zip")
    parser.add_argument("--dev", action="store_true", help="Install dev dependencies")
    parser.add_argument("--dry-run", action="store_true", help="Validate bootstrap/install flow without starting VIKI")
    parser.add_argument("--force-env", action="store_true", help="Rewrite .env from the VIKI template")
    parser.add_argument("--run", action="store_true", help="Start VIKI immediately after installation")
    parser.add_argument("--update", action="store_true", help="Upgrade the local VIKI install in place")
    parser.add_argument("--host", default=os.environ.get("VIKI_BOOTSTRAP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("VIKI_BOOTSTRAP_PORT", "8787")))
    args = parser.parse_args()

    root = project_root(Path(args.path))
    bootstrap(root=root, install_dev=args.dev, force_env=args.force_env, run_server=(args.run and not args.dry_run), host=args.host, port=args.port, update=args.update)
