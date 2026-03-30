# MCP Integration Guide

OpenViking can be used as an [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server, allowing any MCP-compatible client to access its memory and resource capabilities.

## Transport Modes

OpenViking supports two MCP transport modes:

| | HTTP (SSE) | stdio |
|---|---|---|
| **How it works** | Single long-running server process; clients connect via HTTP | Host spawns a new OpenViking process per session |
| **Multi-session safe** | ✅ Yes — single process, no lock contention | ⚠️ **No** — multiple processes contend for the same data directory |
| **Recommended for** | Production, multi-agent, multi-session | Single-session local development only |
| **Setup complexity** | Requires running `openviking-server` separately | Zero setup — host manages the process |

### Choosing the Right Transport

- **Use HTTP** if your host opens multiple sessions, runs multiple agents, or needs concurrent access.
- **Use stdio** only for single-session, single-agent local setups where simplicity is the priority.

> ⚠️ **Important:** When an MCP host spawns multiple stdio OpenViking processes (e.g., one per chat session), all instances compete for the same underlying data directory. This causes **lock/resource contention** in the storage layer (AGFS and VectorDB).
>
> Symptoms include misleading errors such as:
> - `Collection 'context' does not exist`
> - `Transport closed`
> - Intermittent search failures
>
> **The root cause is not a broken index** — it is multiple processes contending for the same storage files. Switch to HTTP mode to resolve this. See [Troubleshooting](#troubleshooting) for details.

## Setup

### Prerequisites

1. OpenViking installed (`pip install openviking` or from source)
2. A valid configuration file (see [Configuration Guide](01-configuration.md))
3. For HTTP mode: `openviking-server` running (see [Deployment Guide](03-deployment.md))

### HTTP Mode (Recommended)

Start the OpenViking server first:

```bash
openviking-server --config /path/to/config.yaml
# Default: http://localhost:1933
```

Then configure your MCP client to connect via HTTP.

### stdio Mode

No separate server needed — the MCP host spawns OpenViking directly.

## Client Configuration

### Claude Code (CLI)

**HTTP mode:**

```bash
claude mcp add openviking \
  --transport sse \
  "http://localhost:1933/mcp"
```

**stdio mode:**

```bash
claude mcp add openviking \
  --transport stdio \
  -- python -m openviking.server --transport stdio \
     --config /path/to/config.yaml
```

### Claude Desktop

Edit `claude_desktop_config.json`:

**HTTP mode:**

```json
{
  "mcpServers": {
    "openviking": {
      "url": "http://localhost:1933/mcp"
    }
  }
}
```

**stdio mode:**

```json
{
  "mcpServers": {
    "openviking": {
      "command": "python",
      "args": [
        "-m", "openviking.server",
        "--transport", "stdio",
        "--config", "/path/to/config.yaml"
      ]
    }
  }
}
```

### Cursor

In Cursor Settings → MCP:

**HTTP mode:**

```json
{
  "mcpServers": {
    "openviking": {
      "url": "http://localhost:1933/mcp"
    }
  }
}
```

### Codex

Configure Codex to use the same HTTP MCP endpoint pattern as other MCP hosts:

```json
{
  "mcpServers": {
    "openviking": {
      "url": "http://localhost:2033/mcp"
    }
  }
}
```

For multi-session coding workflows, prefer the dedicated `examples/mcp-query/server.py`
HTTP server and keep one stable OpenViking `session_id` per external task.

**stdio mode:**

```json
{
  "mcpServers": {
    "openviking": {
      "command": "python",
      "args": [
        "-m", "openviking.server",
        "--transport", "stdio",
        "--config", "/path/to/config.yaml"
      ]
    }
  }
}
```

### OpenClaw

In your OpenClaw configuration (`openclaw.json` or `openclaw.yaml`):

**HTTP mode (recommended):**

```json
{
  "mcp": {
    "servers": {
      "openviking": {
        "url": "http://localhost:1933/mcp"
      }
    }
  }
}
```

**stdio mode:**

```json
{
  "mcp": {
    "servers": {
      "openviking": {
        "command": "python",
        "args": [
          "-m", "openviking.server",
          "--transport", "stdio",
          "--config", "/path/to/config.yaml"
        ]
      }
    }
  }
}
```

## Available MCP Tools

Once connected, OpenViking exposes the following MCP tools:

| Tool | Description |
|------|-------------|
| `query` | Full RAG pipeline: search plus answer generation |
| `search` | Semantic search only |
| `add_resource` | Add a file, directory, or URL for indexing |
| `ensure_session` | Create or materialize a stable task session |
| `get_session` | Inspect session metadata |
| `add_session_message` | Append a low-level plain-text message |
| `record_session_usage` | Record which contexts or skills were actually used |
| `sync_progress` | Persist structured task progress after meaningful turns |
| `commit_session` | Archive messages and trigger memory extraction |
| `get_task` | Poll async commit status |

Refer to OpenViking's tool documentation for full parameter details.

## Recommended Agent Workflow

For Cursor, Codex, Paperclip runners, and similar coding agents, use a retrieve-first,
writeback-third loop:

1. Connect to OpenViking over HTTP MCP.
2. At task start, call `ensure_session` with a stable external task ID.
3. Before answering implementation questions, call `search` or `query`. Narrow the URI scope
   as soon as possible to the relevant repo or subdirectory.
4. After each meaningful turn, call `sync_progress` with:
   - `objective`
   - `assistant_summary`
   - `changed_files`
   - `decisions`
   - `next_steps`
   - `contexts_used` when applicable
5. Keep `auto_commit=true` and `wait_for_commit=false` for interactive chats.
6. Use `commit_session(wait=true)` only in automation, validation, or end-of-task flows.

Important integration note: publishing a task in an external orchestrator such as Paperclip
does not itself trigger OpenViking retrieval or session sync. The host prompt, agent runtime,
or workflow must explicitly invoke the MCP tools above.

## Troubleshooting

### `Collection 'context' does not exist`

**Likely cause:** Multiple stdio MCP instances contending for the same data directory.

**Fix:** Switch to HTTP mode. If you must use stdio, ensure only one OpenViking process accesses a given data directory at a time.

### `Transport closed`

**Likely cause:** The MCP stdio process crashed or was killed due to resource contention. Can also occur when a client holds a stale connection after the backend was restarted.

**Fix:**
1. Switch to HTTP mode to avoid contention.
2. If using HTTP: reload the MCP connection in your client (restart the session or reconnect).

### Connection refused on HTTP endpoint

**Likely cause:** `openviking-server` is not running, or is running on a different port.

**Fix:** Verify the server is running:

```bash
curl http://localhost:1933/health
# Expected: {"status": "ok"}
```

### Authentication errors

**Likely cause:** API key mismatch between client config and server config.

**Fix:** Ensure the API key in your MCP client configuration matches the one in your OpenViking server configuration. See [Authentication Guide](04-authentication.md).

## References

- [MCP Specification](https://modelcontextprotocol.io/)
- [OpenViking Configuration](01-configuration.md)
- [OpenViking Deployment](03-deployment.md)
- [Related issue: stdio contention (#473)](https://github.com/volcengine/OpenViking/issues/473)
