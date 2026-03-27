# OpenViking MCP Server

MCP (Model Context Protocol) HTTP server that exposes OpenViking RAG and session-sync
capabilities as tools.

## Tools

| Tool | Description |
|------|-------------|
| `query` | Full RAG pipeline — search + LLM answer generation |
| `search` | Semantic search only, returns matching documents |
| `add_resource` | Add files, directories, or URLs to the database |
| `ensure_session` | Create a new session or materialize a named task session |
| `get_session` | Inspect session metadata |
| `add_session_message` | Low-level message append for custom flows |
| `record_session_usage` | Record contexts or skills that were actually used |
| `commit_session` | Archive messages and trigger memory extraction |
| `get_task` | Poll async commit task status |
| `sync_progress` | Best-practice helper for post-conversation progress syncing |

## Quick Start

```bash
# Setup config
cp ov.conf.example ov.conf
# Edit ov.conf with your API keys

# Install dependencies
uv sync

# Start the server (streamable HTTP on port 2033)
uv run server.py
```

The server will be available at `http://127.0.0.1:2033/mcp`.

## Best-Practice Progress Sync

If you want Cursor, Codex, or another MCP-capable agent to update OpenViking after
each meaningful conversation turn, use one stable `session_id` per task and call
`sync_progress` instead of dumping the raw transcript.

Recommended pattern:

1. Call `ensure_session("repo-task-123")` once at task start.
2. After each meaningful reply, call `sync_progress(...)` with:
   - `objective`
   - `user_message`
   - `assistant_summary`
   - `completed`
   - `changed_files`
   - `decisions`
   - `next_steps`
3. Keep `auto_commit=true`.
4. Keep `wait_for_commit=false` during interactive chats to avoid extra latency.
5. Use `commit_session(wait=true)` only in validation or automation flows where you
   need to block until extraction finishes.

Design rules:

- Reuse the same session for the same task.
- Log net-new progress, not full chat history.
- Always include changed files and next steps when they exist.
- Record actual contexts/skills used so `active_count` and provenance stay meaningful.

Example payload:

```json
{
  "session_id": "openviking-mcp-session-sync",
  "objective": "Add session writeback tools to the MCP server",
  "user_message": "Make Cursor sync meaningful progress into OpenViking",
  "assistant_summary": "Added ensure_session, sync_progress, and commit_session MCP tools.",
  "completed": [
    "Created a reusable session progress helper",
    "Exposed structured progress syncing in the MCP server"
  ],
  "changed_files": [
    "examples/common/session_progress.py",
    "examples/mcp-query/server.py",
    "examples/mcp-query/README.md"
  ],
  "decisions": [
    "Persist structured summaries instead of raw transcript dumps"
  ],
  "next_steps": [
    "Add tests for sync_progress orchestration"
  ],
  "status": "in_progress",
  "auto_commit": true,
  "wait_for_commit": false
}
```

## Connect from Claude

```bash
# Add as MCP server in Claude CLI
claude mcp add --transport http openviking http://localhost:2033/mcp
```

Or add to `.mcp.json`:

```json
{
  "mcpServers": {
    "openviking": {
      "type": "http",
      "url": "http://localhost:2033/mcp"
    }
  }
}
```

## Options

```
uv run server.py [OPTIONS]

  --config PATH       Config file path (default: ./ov.conf, env: OV_CONFIG)
  --data PATH         Data directory path (default: ./data, env: OV_DATA)
  --host HOST         Bind address (default: 127.0.0.1)
  --port PORT         Listen port (default: 2033, env: OV_PORT)
  --transport TYPE    streamable-http | stdio (default: streamable-http)
```

## Testing with MCP Inspector

```bash
npx @modelcontextprotocol/inspector
# Connect to http://localhost:2033/mcp
```
