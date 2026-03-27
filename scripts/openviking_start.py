#!/usr/bin/env python3
"""Repository-local OpenViking launcher.

This wrapper keeps startup pinned to this checkout:
- bootstraps the repository `.venv` when needed
- rebuilds native/runtime artifacts when they are missing
- chooses a usable config file automatically
- hands off to the real `openviking-server` bootstrap inside the repo env
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
OPENVIKING_CONFIG_ENV = "OPENVIKING_CONFIG_FILE"
USER_DEFAULT_CONFIG = Path.home() / ".openviking" / "ov.conf"
REPO_DEFAULT_CONFIG = REPO_ROOT / "ov.local.json"


class LaunchError(RuntimeError):
    """Raised when the local launcher cannot prepare the runtime."""


def _venv_python_path() -> Path:
    if os.name == "nt":
        return REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    return REPO_ROOT / ".venv" / "bin" / "python"


def _agfs_binary_path() -> Path:
    name = "agfs-server.exe" if os.name == "nt" else "agfs-server"
    return REPO_ROOT / "openviking" / "bin" / name


def _ov_binary_path() -> Path:
    name = "ov.exe" if os.name == "nt" else "ov"
    return REPO_ROOT / "openviking" / "bin" / name


def _agfs_library_present() -> bool:
    names = ["libagfsbinding.dll", "libagfsbinding.dylib", "libagfsbinding.so"]
    return any((REPO_ROOT / "openviking" / "lib" / name).exists() for name in names)


def _engine_artifact_present() -> bool:
    engine_dir = REPO_ROOT / "openviking" / "storage" / "vectordb" / "engine"
    patterns = ("*.so", "*.pyd")
    return any(any(engine_dir.glob(pattern)) for pattern in patterns)


def _runtime_artifacts_present() -> bool:
    return (
        _agfs_binary_path().exists()
        and _ov_binary_path().exists()
        and _agfs_library_present()
        and _engine_artifact_present()
    )


def _iter_local_prebuilt_packages() -> Iterable[Path]:
    patterns = (
        "examples/**/.venv/lib/python*/site-packages/openviking",
        "examples/**/.venv/Lib/site-packages/openviking",
    )
    seen: set[Path] = set()
    for pattern in patterns:
        for candidate in REPO_ROOT.glob(pattern):
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            yield resolved


def _copy_matching_files(source_dir: Path, target_dir: Path, patterns: Sequence[str]) -> bool:
    if not source_dir.exists():
        return False

    copied = False
    target_dir.mkdir(parents=True, exist_ok=True)
    for pattern in patterns:
        for candidate in source_dir.glob(pattern):
            if not candidate.is_file():
                continue
            shutil.copy2(candidate, target_dir / candidate.name)
            copied = True
    return copied


def _hydrate_runtime_artifacts_from_local_cache() -> bool:
    for package_dir in _iter_local_prebuilt_packages():
        copied_any = False
        copied_any |= _copy_matching_files(
            package_dir / "bin",
            REPO_ROOT / "openviking" / "bin",
            ("agfs-server", "agfs-server.exe", "ov", "ov.exe"),
        )
        copied_any |= _copy_matching_files(
            package_dir / "lib",
            REPO_ROOT / "openviking" / "lib",
            ("libagfsbinding.so", "libagfsbinding.dylib", "libagfsbinding.dll"),
        )
        copied_any |= _copy_matching_files(
            package_dir / "storage" / "vectordb" / "engine",
            REPO_ROOT / "openviking" / "storage" / "vectordb" / "engine",
            ("*.so", "*.pyd"),
        )
        if copied_any and _runtime_artifacts_present():
            print(f"[openviking] Reused local prebuilt artifacts from {package_dir}...")
            return True
    return False


def _has_explicit_config(argv: Sequence[str]) -> bool:
    for index, arg in enumerate(argv):
        if arg == "--config" and index + 1 < len(argv):
            return True
        if arg.startswith("--config="):
            return True
    return False


def resolve_config_path(argv: Sequence[str]) -> Path:
    """Resolve the config path that should be passed to the server bootstrap."""
    for index, arg in enumerate(argv):
        if arg == "--config":
            if index + 1 >= len(argv):
                raise LaunchError("`--config` requires a file path.")
            candidate = Path(argv[index + 1]).expanduser()
            if not candidate.exists():
                raise LaunchError(f"Config file does not exist: {candidate}")
            return candidate.resolve()
        if arg.startswith("--config="):
            candidate = Path(arg.split("=", 1)[1]).expanduser()
            if not candidate.exists():
                raise LaunchError(f"Config file does not exist: {candidate}")
            return candidate.resolve()

    env_value = os.environ.get(OPENVIKING_CONFIG_ENV)
    if env_value:
        candidate = Path(env_value).expanduser()
        if not candidate.exists():
            raise LaunchError(
                f"{OPENVIKING_CONFIG_ENV} points to a missing file: {candidate}"
            )
        return candidate.resolve()

    if USER_DEFAULT_CONFIG.exists():
        return USER_DEFAULT_CONFIG.resolve()

    if REPO_DEFAULT_CONFIG.exists():
        return REPO_DEFAULT_CONFIG.resolve()

    raise LaunchError(
        "No OpenViking config file found. "
        f"Create {USER_DEFAULT_CONFIG} or add {REPO_DEFAULT_CONFIG.name} to the repo."
    )


def build_bootstrap_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    env.setdefault("SETUPTOOLS_SCM_PRETEND_VERSION_FOR_OPENVIKING", "0.0.0")
    return env


def _run(cmd: Sequence[str], *, cwd: Path) -> None:
    subprocess.run(list(cmd), cwd=str(cwd), env=build_bootstrap_env(), check=True)


def _python_imports_ready(python_bin: Path) -> bool:
    if not python_bin.exists():
        return False

    probe = [
        str(python_bin),
        "-c",
        "import requests, fastapi, uvicorn, openai; import openviking_cli.server_bootstrap",
    ]
    result = subprocess.run(
        probe,
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def ensure_runtime_ready() -> Path:
    """Prepare the repository venv and native artifacts if they are missing."""
    python_bin = _venv_python_path()

    if not shutil.which("uv"):
        raise LaunchError("`uv` is required but was not found in PATH.")

    if not _python_imports_ready(python_bin):
        print("[openviking] Bootstrapping repository virtualenv with `uv sync --all-extras`...")
        _run(["uv", "sync", "--all-extras"], cwd=REPO_ROOT)

    python_bin = _venv_python_path()
    if not _python_imports_ready(python_bin):
        raise LaunchError("Repository virtualenv is still incomplete after `uv sync`.")

    if not _runtime_artifacts_present():
        _hydrate_runtime_artifacts_from_local_cache()

    if not _runtime_artifacts_present():
        print("[openviking] Building native/runtime artifacts with `uv pip install -e . --force-reinstall`...")
        _run(["uv", "pip", "install", "-e", ".", "--force-reinstall"], cwd=REPO_ROOT)

    if not _runtime_artifacts_present():
        raise LaunchError("Native/runtime artifacts are still missing after reinstall.")

    return python_bin


def build_server_argv(forwarded_argv: Sequence[str], config_path: Path) -> list[str]:
    argv = list(forwarded_argv)
    if not _has_explicit_config(argv):
        argv = ["--config", str(config_path), *argv]
    return argv


def main(argv: Iterable[str] | None = None) -> int:
    forwarded_argv = list(sys.argv[1:] if argv is None else argv)

    try:
        config_path = resolve_config_path(forwarded_argv)
        python_bin = ensure_runtime_ready()
    except (LaunchError, subprocess.CalledProcessError) as exc:
        print(f"[openviking] {exc}", file=sys.stderr)
        return 1

    os.chdir(REPO_ROOT)
    cmd = [
        str(python_bin),
        "-m",
        "openviking_cli.server_bootstrap",
        *build_server_argv(forwarded_argv, config_path),
    ]
    os.execv(str(python_bin), cmd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
