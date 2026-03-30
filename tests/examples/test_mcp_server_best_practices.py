# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

"""Tests for OpenViking MCP server guidance and workflow resources."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVER_PATH = ROOT / "examples" / "mcp-query" / "server.py"
EXAMPLES_DIR = ROOT / "examples"


class FakeFastMCP:
    """Minimal FastMCP test double that records tools/resources/instructions."""

    def __init__(self, **kwargs):
        self.instructions = kwargs.get("instructions", "")
        self.resources: dict[str, object] = {}
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator

    def resource(self, uri: str):
        def decorator(func):
            self.resources[uri] = func
            return func

        return decorator


def _load_server_module():
    mcp_module = types.ModuleType("mcp")
    server_module = types.ModuleType("mcp.server")
    fastmcp_module = types.ModuleType("mcp.server.fastmcp")
    fastmcp_module.FastMCP = FakeFastMCP

    sys.modules["mcp"] = mcp_module
    sys.modules["mcp.server"] = server_module
    sys.modules["mcp.server.fastmcp"] = fastmcp_module

    if str(EXAMPLES_DIR) not in sys.path:
        sys.path.insert(0, str(EXAMPLES_DIR))

    spec = importlib.util.spec_from_file_location("test_openviking_mcp_server", SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_create_server_instructions_include_task_workflow():
    module = _load_server_module()

    server = module.create_server()

    assert "retrieve first" in server.instructions
    assert "ensure_session" in server.instructions
    assert "sync_progress" in server.instructions
    assert "wait_for_commit=false" in server.instructions
    assert "Cursor, Codex, and Paperclip" in server.instructions


def test_best_practice_resource_exposes_explicit_agent_guidance():
    module = _load_server_module()

    server = module.create_server()
    resource = server.resources["openviking://best-practices/task-workflow"]
    text = resource()

    assert "Use one stable session per task" in text
    assert "Write back structured progress" in text
    assert "Prefer HTTP MCP transport" in text
    assert "Publishing a task alone does not trigger retrieval" in text
