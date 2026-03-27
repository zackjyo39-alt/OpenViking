from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_launcher():
    repo_root = Path(__file__).resolve().parents[1]
    launcher_path = repo_root / "scripts" / "openviking_start.py"
    spec = importlib.util.spec_from_file_location("openviking_start", launcher_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_resolve_config_prefers_explicit_arg(tmp_path, monkeypatch):
    launcher = _load_launcher()
    explicit = tmp_path / "explicit.json"
    explicit.write_text("{}", encoding="utf-8")
    monkeypatch.delenv(launcher.OPENVIKING_CONFIG_ENV, raising=False)
    monkeypatch.setattr(launcher, "USER_DEFAULT_CONFIG", tmp_path / "missing-user.json")
    monkeypatch.setattr(launcher, "REPO_DEFAULT_CONFIG", tmp_path / "missing-repo.json")

    resolved = launcher.resolve_config_path(["--config", str(explicit)])

    assert resolved == explicit.resolve()


def test_resolve_config_prefers_env_before_repo_default(tmp_path, monkeypatch):
    launcher = _load_launcher()
    env_config = tmp_path / "env.json"
    repo_config = tmp_path / "repo.json"
    env_config.write_text("{}", encoding="utf-8")
    repo_config.write_text("{}", encoding="utf-8")
    monkeypatch.setenv(launcher.OPENVIKING_CONFIG_ENV, str(env_config))
    monkeypatch.setattr(launcher, "USER_DEFAULT_CONFIG", tmp_path / "missing-user.json")
    monkeypatch.setattr(launcher, "REPO_DEFAULT_CONFIG", repo_config)

    resolved = launcher.resolve_config_path([])

    assert resolved == env_config.resolve()


def test_build_server_argv_injects_config_when_missing(tmp_path):
    launcher = _load_launcher()
    config_path = tmp_path / "ov.local.json"

    argv = launcher.build_server_argv(["--port", "2048"], config_path)

    assert argv[:2] == ["--config", str(config_path)]
    assert argv[2:] == ["--port", "2048"]


def test_build_server_argv_respects_existing_config(tmp_path):
    launcher = _load_launcher()
    explicit = tmp_path / "explicit.json"
    config_path = tmp_path / "ov.local.json"

    argv = launcher.build_server_argv(["--config", str(explicit)], config_path)

    assert argv == ["--config", str(explicit)]


def test_build_bootstrap_env_sets_local_version_fallback():
    launcher = _load_launcher()

    env = launcher.build_bootstrap_env({})

    assert env["SETUPTOOLS_SCM_PRETEND_VERSION_FOR_OPENVIKING"] == "0.0.0"
