#!/usr/bin/env bash
# OpenViking MCP HTTP server for Cursor (and other MCP clients).
# Uses PyPI wheels for `openviking` + `mcp` (no local AGFS build).
#
# Prerequisite: same ov.conf + workspace as openviking-server (Ollama 等已配置).
# Defaults align with deploy/start-openviking-ollama.sh generated config.
#
# Usage:
#   ./deploy/start-openviking-mcp-for-cursor.sh
#   OV_CONFIG=/path/to/ov.json OV_DATA=/path/to/workspace ./deploy/start-openviking-mcp-for-cursor.sh --port 2033

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MCP_DIR="${REPO_ROOT}/examples/mcp-query"

RUNTIME_ROOT="${OPENVIKING_RUNTIME_DIR:-${XDG_CACHE_HOME:-${HOME}/.cache}/openviking-ollama}"
: "${OV_CONFIG:=${RUNTIME_ROOT}/ov.generated.json}"
: "${OV_DATA:=${HOME}/openviking_workspace_ollama}"
: "${OV_PORT:=2033}"

if [[ ! -f "${OV_CONFIG}" ]]; then
  echo "error: OV_CONFIG not found: ${OV_CONFIG}" >&2
  echo "  Run deploy/start-openviking-ollama.sh once, or set OV_CONFIG to your ov.conf / ov.generated.json" >&2
  exit 1
fi

if [[ ! -d "${OV_DATA}" ]]; then
  echo "error: OV_DATA directory not found: ${OV_DATA}" >&2
  exit 1
fi

cd "${MCP_DIR}"

if [[ ! -x .venv/bin/python ]]; then
  echo "Creating venv in ${MCP_DIR}/.venv (Python 3.12)..."
  uv venv --python 3.12
fi

echo "Ensuring openviking + mcp (PyPI)..."
uv pip install -q "openviking>=0.1.6" "mcp>=1.8.0"

export OV_CONFIG OV_DATA OV_PORT
echo "Starting OpenViking MCP at http://127.0.0.1:${OV_PORT}/mcp"
echo "  OV_CONFIG=${OV_CONFIG}"
echo "  OV_DATA=${OV_DATA}"
exec .venv/bin/python server.py --host 127.0.0.1 --port "${OV_PORT}" "$@"
