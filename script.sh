#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$REPO_ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  if ! command -v uv >/dev/null 2>&1; then
    echo "[openviking-onboard] uv is required but was not found in PATH." >&2
    exit 1
  fi

  echo "[openviking-onboard] Bootstrapping repository virtualenv..."
  env SETUPTOOLS_SCM_PRETEND_VERSION_FOR_OPENVIKING=0.0.0 \
    uv sync --all-extras --no-install-project --python 3.13
fi

exec "$PYTHON_BIN" "$REPO_ROOT/scripts/project_onboard.py" "$@"
