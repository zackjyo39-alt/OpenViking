# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the MCP session progress helper."""

from pathlib import Path
from types import SimpleNamespace
import sys


EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"
if str(EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(EXAMPLES_DIR))

from common.session_progress import SessionProgressManager, build_progress_update


class FakeSession:
    """Small in-memory session stub for orchestration tests."""

    def __init__(self, session_id: str, commit_result=None):
        self.session_id = session_id
        self.messages = []
        self.stats = SimpleNamespace(contexts_used=0, skills_used=0)
        self._commit_result = commit_result or {
            "session_id": session_id,
            "status": "accepted",
            "task_id": "task-1",
            "archive_uri": f"viking://session/default/{session_id}/history/archive_001",
            "archived": True,
        }
        self.used_calls = []

    async def load(self) -> None:
        return None

    def add_message(self, role: str, parts: list[object]) -> None:
        self.messages.append(
            {
                "role": role,
                "text": parts[0].text,
            }
        )

    def used(self, contexts=None, skill=None) -> None:
        contexts = contexts or []
        self.stats.contexts_used += len(contexts)
        self.stats.skills_used += int(skill is not None)
        self.used_calls.append(
            {
                "contexts": contexts,
                "skill": skill,
            }
        )

    def commit(self):
        return dict(self._commit_result)


class FakeClient:
    """Small sync client stub with deterministic task responses."""

    def __init__(self, task_responses=None):
        self.sessions = {}
        self.created_session_ids = []
        self.get_session_calls = []
        self.task_responses = list(task_responses or [])

    def create_session(self):
        session_id = f"generated-{len(self.created_session_ids) + 1}"
        self.created_session_ids.append(session_id)
        self.sessions.setdefault(session_id, FakeSession(session_id))
        return {"session_id": session_id, "user": {"user_id": "default", "agent_id": "default"}}

    def get_session(self, session_id: str, *, auto_create: bool = False):
        self.get_session_calls.append((session_id, auto_create))
        if auto_create:
            self.sessions.setdefault(session_id, FakeSession(session_id))
        return {
            "session_id": session_id,
            "message_count": len(self.sessions.setdefault(session_id, FakeSession(session_id)).messages),
            "commit_count": 0,
        }

    def session(self, session_id=None, must_exist: bool = False):
        assert session_id is not None
        if must_exist and session_id not in self.sessions:
            raise KeyError(session_id)
        return self.sessions.setdefault(session_id, FakeSession(session_id))

    def get_task(self, task_id: str):
        if self.task_responses:
            return self.task_responses.pop(0)
        return {"task_id": task_id, "status": "completed", "result": {"memories_extracted": 1}}


def test_build_progress_update_contains_structured_sections():
    text = build_progress_update(
        objective="Add progress sync",
        assistant_summary="Added the MCP helper and session tools.",
        completed=["Created helper module"],
        changed_files=["examples/common/session_progress.py"],
        decisions=["Use structured updates instead of raw transcript dumps"],
        next_steps=["Add tests"],
        status="in_progress",
    )

    assert "# Progress Update" in text
    assert "Objective: Add progress sync" in text
    assert "Status: in_progress" in text
    assert "## Summary" in text
    assert "## Completed" in text
    assert "## Changed Files" in text
    assert "## Decisions" in text
    assert "## Next Steps" in text


def test_sync_progress_records_messages_usage_and_commit():
    client = FakeClient()
    manager = SessionProgressManager(client)

    result = manager.sync_progress(
        session_id="task-123",
        objective="Persist MCP progress",
        user_message="Make the agent write meaningful progress into OpenViking",
        assistant_summary="Added ensure_session and sync_progress tools.",
        completed=["Created the progress helper"],
        changed_files=["examples/mcp-query/server.py"],
        decisions=["Keep one stable session per task"],
        next_steps=["Write tests"],
        contexts_used=["viking://resources/docs/agent-sync.md"],
        skill={
            "uri": "viking://skills/search-web",
            "input": "session sync",
            "output": "found relevant docs",
            "success": True,
        },
        auto_commit=True,
        wait_for_commit=False,
    )

    session = client.session("task-123")

    assert client.get_session_calls[0] == ("task-123", True)
    assert result["session_id"] == "task-123"
    assert result["messages_logged"] == 2
    assert result["commit"]["task_id"] == "task-1"
    assert session.messages[0]["role"] == "user"
    assert session.messages[1]["role"] == "assistant"
    assert "## Changed Files" in session.messages[1]["text"]
    assert session.used_calls == [
        {
            "contexts": ["viking://resources/docs/agent-sync.md"],
            "skill": {
                "uri": "viking://skills/search-web",
                "input": "session sync",
                "output": "found relevant docs",
                "success": True,
            },
        }
    ]


def test_commit_session_waits_for_async_task_completion():
    client = FakeClient(
        task_responses=[
            {"task_id": "task-1", "status": "running"},
            {
                "task_id": "task-1",
                "status": "completed",
                "result": {"memories_extracted": {"patterns": 1}},
            },
        ]
    )
    client.sessions["task-123"] = FakeSession("task-123")
    manager = SessionProgressManager(client)

    result = manager.commit_session(
        "task-123",
        wait=True,
        timeout_sec=0.1,
        poll_interval_sec=0.001,
    )

    assert result["commit"]["task_id"] == "task-1"
    assert result["task"]["status"] == "completed"
    assert result["task"]["result"]["memories_extracted"]["patterns"] == 1
