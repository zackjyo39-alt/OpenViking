#!/usr/bin/env bash
# OpenViking + local or remote Ollama (OpenAI-compatible /v1).
# Usage: ./start-openviking-ollama.sh
# VPS: copy deploy/.env.example -> deploy/.env, set OLLAMA_* and OPENVIKING_HOST=0.0.0.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEMPLATE="${SCRIPT_DIR}/ov.ollama.conf.template"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env}"

# Defaults (override via environment or deploy/.env)
: "${OLLAMA_API_BASE:=http://127.0.0.1:11434/v1}"
: "${OLLAMA_CHAT_MODEL:=qwen3.5:4b}"
: "${OLLAMA_EMBED_MODEL:=nomic-embed-text}"
: "${EMBEDDING_DIMENSION:=768}"
: "${OPENVIKING_WORKSPACE:=${HOME}/openviking_workspace_ollama}"
: "${OPENVIKING_HOST:=127.0.0.1}"
: "${OPENVIKING_PORT:=1933}"
: "${OPENVIKING_VLM_API_KEY:=ollama}"
: "${OPENVIKING_LOG_LEVEL:=INFO}"
: "${OPENVIKING_VLM_MAX_CONCURRENT:=20}"
: "${OPENVIKING_EMBED_MAX_CONCURRENT:=10}"
: "${OPENVIKING_USE_UVX:=1}"

RUNTIME_ROOT="${OPENVIKING_RUNTIME_DIR:-${XDG_CACHE_HOME:-${HOME}/.cache}/openviking-ollama}"
GENERATED_CONF="${RUNTIME_ROOT}/ov.generated.json"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${ENV_FILE}"
  set +a
fi

if [[ ! -f "${TEMPLATE}" ]]; then
  echo "error: missing template ${TEMPLATE}" >&2
  exit 1
fi

mkdir -p "${RUNTIME_ROOT}"
mkdir -p "${OPENVIKING_WORKSPACE}"

export OLLAMA_API_BASE OLLAMA_CHAT_MODEL OLLAMA_EMBED_MODEL EMBEDDING_DIMENSION
export OPENVIKING_WORKSPACE OPENVIKING_LOG_LEVEL OPENVIKING_VLM_API_KEY
export OPENVIKING_VLM_MAX_CONCURRENT OPENVIKING_EMBED_MAX_CONCURRENT

python3 - "${TEMPLATE}" "${GENERATED_CONF}" <<'PY'
import os
import re
import sys
from pathlib import Path

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
text = src.read_text(encoding="utf-8")
pat = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")

def repl(m: re.Match[str]) -> str:
    key = m.group(1)
    if key not in os.environ:
        sys.exit(f"error: placeholder ${{{key}}} not set in environment")
    return os.environ[key]

out = pat.sub(repl, text)
dst.write_text(out, encoding="utf-8")
print(f"Wrote {dst}", file=sys.stderr)
PY

export OPENVIKING_CONFIG_FILE="${GENERATED_CONF}"

if [[ "${OPENVIKING_USE_UVX}" == "1" ]]; then
  exec uvx --from openviking openviking-server \
    --config "${GENERATED_CONF}" \
    --host "${OPENVIKING_HOST}" \
    --port "${OPENVIKING_PORT}" \
    "$@"
else
  if ! command -v openviking-server >/dev/null 2>&1; then
    echo "error: openviking-server not on PATH; install openviking or set OPENVIKING_USE_UVX=1" >&2
    exit 1
  fi
  exec openviking-server \
    --config "${GENERATED_CONF}" \
    --host "${OPENVIKING_HOST}" \
    --port "${OPENVIKING_PORT}" \
    "$@"
fi
