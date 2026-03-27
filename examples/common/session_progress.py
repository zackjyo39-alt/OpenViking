"""Helpers for syncing task progress into OpenViking sessions.

This module keeps the MCP-facing workflow opinionated:
log net-new progress as structured summaries, not raw transcript dumps.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Protocol, Sequence

from openviking.message.part import TextPart
from openviking_cli.utils import run_async


class SessionLike(Protocol):
    """Subset of the OpenViking Session API used by the MCP helper."""

    session_id: str
    messages: list[Any]
    stats: Any

    async def load(self) -> None: ...

    def add_message(self, role: str, parts: list[Any]) -> Any: ...

    def used(
        self,
        contexts: Optional[list[str]] = None,
        skill: Optional[Dict[str, Any]] = None,
    ) -> None: ...

    def commit(self) -> Dict[str, Any]: ...


class ClientLike(Protocol):
    """Subset of the synchronous OpenViking client used by the helper."""

    def create_session(self) -> Dict[str, Any]: ...

    def get_session(self, session_id: str, *, auto_create: bool = False) -> Dict[str, Any]: ...

    def session(self, session_id: Optional[str] = None, must_exist: bool = False) -> SessionLike: ...

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]: ...


def _clean_text(value: str) -> str:
    return value.strip()


def _normalize_lines(items: Optional[Sequence[str]]) -> list[str]:
    if not items:
        return []
    cleaned: list[str] = []
    for item in items:
        text = str(item).strip()
        if text:
            cleaned.append(text)
    return cleaned


def _append_section(lines: list[str], title: str, items: Sequence[str]) -> None:
    normalized = _normalize_lines(items)
    if not normalized:
        return
    lines.extend(["", f"## {title}"])
    lines.extend(f"- {item}" for item in normalized)


def build_progress_update(
    *,
    objective: str = "",
    assistant_summary: str = "",
    completed: Optional[Sequence[str]] = None,
    changed_files: Optional[Sequence[str]] = None,
    decisions: Optional[Sequence[str]] = None,
    next_steps: Optional[Sequence[str]] = None,
    status: str = "in_progress",
) -> str:
    """Build a compact, structured assistant progress update."""

    objective = _clean_text(objective)
    assistant_summary = _clean_text(assistant_summary)
    status = _clean_text(status) or "in_progress"

    lines = ["# Progress Update", "", f"Status: {status}"]
    if objective:
        lines.append(f"Objective: {objective}")

    if assistant_summary:
        lines.extend(["", "## Summary", assistant_summary])

    _append_section(lines, "Completed", completed or [])
    _append_section(lines, "Changed Files", changed_files or [])
    _append_section(lines, "Decisions", decisions or [])
    _append_section(lines, "Next Steps", next_steps or [])

    return "\n".join(lines).strip()


class SessionProgressManager:
    """Best-practice wrapper for logging progress to OpenViking sessions."""

    def __init__(self, client: ClientLike):
        self._client = client

    def ensure_session(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Create a new session or materialize the named one."""

        if session_id:
            self._client.get_session(session_id, auto_create=True)
            resolved_session_id = session_id
        else:
            result = self._client.create_session()
            resolved_session_id = str(result["session_id"])

        session = self._client.session(resolved_session_id)
        run_async(session.load())
        meta = self._client.get_session(resolved_session_id, auto_create=True)
        return {
            "session_id": resolved_session_id,
            "session": meta,
        }

    def get_session(self, session_id: str) -> Dict[str, Any]:
        """Fetch session metadata."""

        return self._client.get_session(session_id, auto_create=False)

    def _load_session(self, session_id: Optional[str] = None) -> SessionLike:
        session_info = self.ensure_session(session_id)
        session = self._client.session(str(session_info["session_id"]))
        run_async(session.load())
        return session

    def add_message(self, session_id: str, role: str, content: str) -> Dict[str, Any]:
        """Append one plain-text message to a session."""

        content = _clean_text(content)
        if not content:
            raise ValueError("content must not be empty")

        session = self._load_session(session_id)
        session.add_message(role, [TextPart(text=content)])
        return {
            "session_id": session.session_id,
            "message_count": len(session.messages),
        }

    def record_usage(
        self,
        session_id: str,
        *,
        contexts: Optional[Sequence[str]] = None,
        skill: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record actual context or skill usage for the session."""

        normalized_contexts = _normalize_lines(contexts)
        normalized_skill = skill or None

        if not normalized_contexts and not normalized_skill:
            raise ValueError("either contexts or skill must be provided")

        session = self._load_session(session_id)
        session.used(contexts=normalized_contexts, skill=normalized_skill)
        return {
            "session_id": session.session_id,
            "contexts_used": session.stats.contexts_used,
            "skills_used": session.stats.skills_used,
        }

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get background commit task state."""

        return self._client.get_task(task_id)

    def wait_for_task(
        self,
        task_id: str,
        *,
        timeout_sec: float = 60.0,
        poll_interval_sec: float = 1.0,
    ) -> Dict[str, Any]:
        """Poll a background task until it completes or fails."""

        if timeout_sec <= 0:
            raise ValueError("timeout_sec must be > 0")
        if poll_interval_sec <= 0:
            raise ValueError("poll_interval_sec must be > 0")

        deadline = time.monotonic() + timeout_sec
        latest: Optional[Dict[str, Any]] = None
        while time.monotonic() <= deadline:
            latest = self._client.get_task(task_id)
            if latest and latest.get("status") in {"completed", "failed"}:
                return latest
            time.sleep(poll_interval_sec)

        raise TimeoutError(f"Timed out waiting for task {task_id}")

    def commit_session(
        self,
        session_id: str,
        *,
        wait: bool = False,
        timeout_sec: float = 60.0,
        poll_interval_sec: float = 1.0,
    ) -> Dict[str, Any]:
        """Commit a session and optionally wait for the async extraction task."""

        session = self._load_session(session_id)
        commit = session.commit()
        result: Dict[str, Any] = {
            "session_id": session.session_id,
            "commit": commit,
        }

        task_id = commit.get("task_id")
        if wait and task_id:
            result["task"] = self.wait_for_task(
                task_id,
                timeout_sec=timeout_sec,
                poll_interval_sec=poll_interval_sec,
            )

        return result

    def sync_progress(
        self,
        *,
        session_id: Optional[str] = None,
        objective: str = "",
        user_message: str = "",
        assistant_summary: str = "",
        completed: Optional[Sequence[str]] = None,
        changed_files: Optional[Sequence[str]] = None,
        decisions: Optional[Sequence[str]] = None,
        next_steps: Optional[Sequence[str]] = None,
        status: str = "in_progress",
        contexts_used: Optional[Sequence[str]] = None,
        skill: Optional[Dict[str, Any]] = None,
        auto_commit: bool = True,
        wait_for_commit: bool = False,
        commit_timeout_sec: float = 60.0,
        poll_interval_sec: float = 1.0,
    ) -> Dict[str, Any]:
        """Log one structured progress turn and optionally commit it."""

        user_message = _clean_text(user_message)
        assistant_message = build_progress_update(
            objective=objective,
            assistant_summary=assistant_summary,
            completed=completed,
            changed_files=changed_files,
            decisions=decisions,
            next_steps=next_steps,
            status=status,
        )

        if not user_message and not assistant_message:
            raise ValueError("sync_progress requires either user_message or assistant content")

        session = self._load_session(session_id)
        messages_logged = 0

        if user_message:
            session.add_message("user", [TextPart(text=user_message)])
            messages_logged += 1

        if assistant_message:
            session.add_message("assistant", [TextPart(text=assistant_message)])
            messages_logged += 1

        normalized_contexts = _normalize_lines(contexts_used)
        if normalized_contexts or skill:
            session.used(contexts=normalized_contexts, skill=skill)

        result: Dict[str, Any] = {
            "session_id": session.session_id,
            "messages_logged": messages_logged,
            "assistant_message": assistant_message,
            "usage": {
                "contexts_used": len(normalized_contexts),
                "skill_recorded": bool(skill),
            },
        }

        if auto_commit:
            commit = session.commit()
            result["commit"] = commit
            task_id = commit.get("task_id")
            if wait_for_commit and task_id:
                result["task"] = self.wait_for_task(
                    task_id,
                    timeout_sec=commit_timeout_sec,
                    poll_interval_sec=poll_interval_sec,
                )

        return result
