#!/usr/bin/env python3
"""Project onboarding helper for OpenViking-managed workspaces."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests
import tomllib

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SERVER_URL = "http://127.0.0.1:1933"
CONTEXT_RELATIVE_DIR = Path(".openviking/context")
OPENVIKING_CONFIG_ENV = "OPENVIKING_CONFIG_FILE"
USER_DEFAULT_CONFIG = Path.home() / ".openviking" / "ov.conf"
REPO_DEFAULT_CONFIG = REPO_ROOT / "ov.local.json"
AUTO_START_MARKER = "<!-- AUTO-GENERATED: START -->"
AUTO_END_MARKER = "<!-- AUTO-GENERATED: END -->"
CONTEXT_DOCS = {
    "overview.md": "Overview",
    "decisions.md": "Decisions",
    "runbook.md": "Runbook",
    "current-focus.md": "Current Focus",
    "codex-cursor-workflow.md": "Codex Cursor Workflow",
}
ROOT_DOC_SUFFIXES = {".md", ".mdx", ".rst", ".txt"}
DOC_SUFFIXES = {".md", ".mdx", ".rst", ".txt", ".pdf", ".yaml", ".yml", ".json", ".toml"}
DOC_EXCLUDE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".html",
    ".htm",
    ".csv",
    ".parquet",
    ".db",
    ".sqlite",
    ".sqlite3",
}
SOURCE_IGNORE_DIRS = [
    ".git",
    ".venv",
    ".pytest_cache",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".cursor",
    ".openviking",
    "docs",
    "temporary",
    "data",
    "node_modules",
    "dist",
    "build",
    "runtime",
    "coverage",
]
DOCS_IGNORE_DIRS = [
    ".git",
    ".venv",
    "__pycache__",
    ".cursor",
    ".openviking",
    "node_modules",
    "assets",
    "images",
]
SOURCE_EXCLUDES = [
    "*.pyc",
    "*.pyo",
    "*.code-workspace",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.svg",
    "*.html",
    "*.htm",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "*.parquet",
    "*.textClipping",
    "uv.lock",
]
DOCS_INCLUDES = ["*.md", "*.mdx", "*.rst", "*.txt", "*.yaml", "*.yml", "*.json", "*.toml", "*.pdf"]
DOCS_EXCLUDES = [
    "*.html",
    "*.htm",
    "*.svg",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.textClipping",
]


class OnboardError(RuntimeError):
    """Raised when onboarding cannot complete."""


@dataclass(frozen=True)
class ImportSpec:
    """A single import operation into OpenViking."""

    name: str
    path: Path
    to_uri: str
    reason: str
    instruction: str = ""
    ignore_dirs: str | None = None
    include: str | None = None
    exclude: str | None = None
    strict: bool = False
    wait: bool = True
    timeout: float | None = 600.0
    directly_upload_media: bool = False
    preserve_structure: bool | None = True

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "path": str(self.path),
            "to": self.to_uri,
            "reason": self.reason,
            "instruction": self.instruction,
            "wait": self.wait,
            "timeout": self.timeout,
            "strict": self.strict,
            "ignore_dirs": self.ignore_dirs,
            "include": self.include,
            "exclude": self.exclude,
            "directly_upload_media": self.directly_upload_media,
        }
        if self.preserve_structure is not None:
            payload["preserve_structure"] = self.preserve_structure
        return payload

    def to_manifest(self) -> dict[str, object]:
        data = asdict(self)
        data["path"] = str(self.path)
        return data


@dataclass(frozen=True)
class ProjectMetadata:
    """Inferred metadata used to generate context documents."""

    project_name: str
    slug: str
    project_root: Path
    description: str
    python_requirement: str | None
    tech_stack: list[str]
    run_commands: list[str]
    test_commands: list[str]
    top_level_layout: list[str]
    root_docs: list[str]
    selected_docs: list[str]
    focus_docs: list[str]


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "project"


def safe_read_text(path: Path, max_chars: int = 60_000) -> str:
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]


def extract_heading_and_intro(path: Path) -> tuple[str | None, str]:
    text = safe_read_text(path)
    if not text:
        return None, ""

    heading: str | None = None
    paragraph_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if paragraph_lines:
                break
            continue
        if line.startswith("#") and heading is None:
            heading = line.lstrip("#").strip()
            continue
        if line.startswith(("<!--", "```")):
            continue
        if not line.startswith("#"):
            paragraph_lines.append(line)
        if len(" ".join(paragraph_lines)) >= 320:
            break
    return heading, " ".join(paragraph_lines).strip()


def parse_pyproject(project_root: Path) -> dict:
    pyproject_path = project_root / "pyproject.toml"
    if not pyproject_path.exists():
        return {}
    try:
        return tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return {}


def parse_pyproject_dependencies(pyproject_data: dict) -> list[str]:
    project = pyproject_data.get("project", {})
    dependencies = project.get("dependencies", [])
    if not isinstance(dependencies, list):
        return []
    return [str(item) for item in dependencies]


def parse_requirements(path: Path) -> list[str]:
    if not path.exists():
        return []

    dependencies: list[str] = []
    for line in safe_read_text(path, max_chars=100_000).splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("#"):
            continue
        if candidate.startswith(("-", "--")):
            continue
        dependencies.append(candidate)
    return dependencies


def infer_tech_stack(project_root: Path, dependencies: list[str]) -> list[str]:
    lower_deps = [dependency.lower() for dependency in dependencies]
    stack: list[str] = []

    def add(item: str) -> None:
        if item not in stack:
            stack.append(item)

    if (project_root / "pyproject.toml").exists():
        add("Python project managed with pyproject.toml")
    if any("streamlit" in dep for dep in lower_deps):
        add("Streamlit application surface")
    if any("langchain" in dep for dep in lower_deps):
        add("LangChain-based orchestration")
    if any("chromadb" in dep for dep in lower_deps):
        add("ChromaDB vector storage")
    if any("ollama" in dep for dep in lower_deps):
        add("Ollama-backed local model serving")
    if any("sentence-transformers" in dep for dep in lower_deps):
        add("Sentence Transformers embeddings")
    if any("openai" in dep for dep in lower_deps):
        add("OpenAI-compatible client integrations")
    if (project_root / "Dockerfile").exists() or (project_root / "docker-compose.yml").exists():
        add("Containerized development or deployment support")
    if (project_root / "package.json").exists():
        add("Node-based tooling")

    return stack


def is_probably_doc(path: Path) -> bool:
    name = path.name.lower()
    if path.suffix.lower() not in ROOT_DOC_SUFFIXES:
        return False
    if name.startswith(("requirements", "constraints")):
        return False
    return True


def list_root_docs(project_root: Path, max_items: int = 12) -> list[str]:
    candidates: list[str] = []
    for child in sorted(project_root.iterdir()):
        if child.is_file() and not child.name.startswith(".") and is_probably_doc(child):
            candidates.append(child.name)
    return candidates[:max_items]


def _doc_priority(path: Path, project_root: Path) -> tuple[int, float, str]:
    rel_path = path.relative_to(project_root).as_posix()
    rel_lower = rel_path.lower()
    name_lower = path.name.lower()

    priority = 100
    if path.parent == project_root:
        priority -= 60
    if name_lower in {"readme.md", "readme.mdx", "agents.md", "running_guide.md", "quick_fix_guide.md"}:
        priority -= 50
    if rel_lower.startswith("docs/technical/"):
        priority -= 40
    elif rel_lower.startswith("docs/workflows/"):
        priority -= 35
    elif rel_lower.startswith("docs/plans/"):
        priority -= 30
    elif rel_lower.startswith("docs/roadmap/"):
        priority -= 25

    return (priority, -path.stat().st_mtime, rel_lower)


def list_selected_docs(project_root: Path, max_items: int = 16) -> list[str]:
    candidates: list[Path] = []

    for child in project_root.iterdir():
        if child.is_file() and not child.name.startswith(".") and is_probably_doc(child):
            candidates.append(child)

    docs_dir = project_root / "docs"
    if docs_dir.exists():
        for candidate in docs_dir.rglob("*"):
            if not candidate.is_file():
                continue
            suffix = candidate.suffix.lower()
            if suffix in DOC_EXCLUDE_SUFFIXES or suffix not in DOC_SUFFIXES:
                continue
            if candidate.stat().st_size > 2_000_000:
                continue
            candidates.append(candidate)

    unique_candidates = sorted({candidate.resolve() for candidate in candidates}, key=lambda p: _doc_priority(p, project_root))
    return [candidate.relative_to(project_root).as_posix() for candidate in unique_candidates[:max_items]]


def list_focus_docs(project_root: Path, max_items: int = 8) -> list[str]:
    focus_candidates: list[Path] = []
    priority_roots = ["docs/plans", "docs/roadmap", "docs/workflows", "docs/technical"]

    for relative_root in priority_roots:
        root = project_root / relative_root
        if not root.exists():
            continue
        for candidate in root.rglob("*.md"):
            if candidate.is_file():
                focus_candidates.append(candidate)

    for name in ["RUNNING_GUIDE.md", "QUICK_FIX_GUIDE.md", "Readme.md", "README.md"]:
        candidate = project_root / name
        if candidate.exists():
            focus_candidates.append(candidate)

    focus_candidates = sorted({candidate.resolve() for candidate in focus_candidates}, key=lambda p: (-p.stat().st_mtime, p.relative_to(project_root).as_posix()))
    return [candidate.relative_to(project_root).as_posix() for candidate in focus_candidates[:max_items]]


def summarize_top_level_layout(project_root: Path, max_items: int = 12) -> list[str]:
    ignored = {
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cursor",
        "node_modules",
    }
    layout: list[str] = []
    for child in sorted(project_root.iterdir()):
        if child.name.startswith(".") or child.name in ignored:
            continue
        suffix = "/" if child.is_dir() else ""
        layout.append(f"`{child.name}{suffix}`")
        if len(layout) >= max_items:
            break
    return layout


def detect_run_commands(project_root: Path, pyproject_data: dict) -> list[str]:
    commands: list[str] = []

    def add(command: str) -> None:
        if command not in commands:
            commands.append(command)

    if (project_root / "start.sh").exists():
        add("./start.sh")
    if (project_root / "scripts" / "start.py").exists():
        add("python scripts/start.py")
    if (project_root / "rag_chatbox.py").exists():
        add("streamlit run rag_chatbox.py")

    scripts = pyproject_data.get("project", {}).get("scripts", {})
    if isinstance(scripts, dict):
        for script_name in scripts:
            add(f"uv run {script_name}")

    return commands


def detect_test_commands(project_root: Path) -> list[str]:
    commands: list[str] = []
    if (project_root / "tests").exists() or (project_root / "pytest.ini").exists():
        commands.append("pytest")
    if (project_root / "package.json").exists():
        commands.append("npm test")
    return commands


def collect_project_metadata(project_root: Path, project_name: str, slug: str) -> ProjectMetadata:
    pyproject_data = parse_pyproject(project_root)
    dependencies = parse_pyproject_dependencies(pyproject_data)
    dependencies.extend(parse_requirements(project_root / "requirements.txt"))

    description = pyproject_data.get("project", {}).get("description", "")
    if not description:
        _, description = extract_heading_and_intro(project_root / "Readme.md")
    if not description:
        _, description = extract_heading_and_intro(project_root / "README.md")
    if not description:
        description = "Add a concise project summary here."

    python_requirement = pyproject_data.get("project", {}).get("requires-python")
    return ProjectMetadata(
        project_name=project_name,
        slug=slug,
        project_root=project_root,
        description=description,
        python_requirement=python_requirement,
        tech_stack=infer_tech_stack(project_root, dependencies),
        run_commands=detect_run_commands(project_root, pyproject_data),
        test_commands=detect_test_commands(project_root),
        top_level_layout=summarize_top_level_layout(project_root),
        root_docs=list_root_docs(project_root),
        selected_docs=list_selected_docs(project_root),
        focus_docs=list_focus_docs(project_root),
    )


def build_import_specs(
    project_root: Path,
    slug: str,
    context_dir: Path,
    *,
    wait: bool,
    timeout: float,
) -> list[ImportSpec]:
    specs = [
        ImportSpec(
            name="source",
            path=project_root,
            to_uri=f"viking://resources/projects/{slug}/source",
            reason="Project source, configuration, and top-level guides for implementation work.",
            ignore_dirs=",".join(SOURCE_IGNORE_DIRS),
            exclude=",".join(SOURCE_EXCLUDES),
            wait=wait,
            timeout=timeout,
        )
    ]

    docs_dir = project_root / "docs"
    if docs_dir.exists():
        specs.append(
            ImportSpec(
                name="docs",
                path=docs_dir,
                to_uri=f"viking://resources/projects/{slug}/docs",
                reason="Curated project documentation for architecture, workflows, and operational context.",
                ignore_dirs=",".join(DOCS_IGNORE_DIRS),
                include=",".join(DOCS_INCLUDES),
                exclude=",".join(DOCS_EXCLUDES),
                wait=wait,
                timeout=timeout,
            )
        )

    specs.append(
        ImportSpec(
            name="context",
            path=context_dir,
            to_uri=f"viking://resources/projects/{slug}/context",
            reason="Generated context pack for Codex and Cursor retrieval before coding.",
            include="*.md,*.json",
            wait=wait,
            timeout=timeout,
        )
    )
    return specs


def render_generated_block(lines: list[str]) -> str:
    return "\n".join([AUTO_START_MARKER, *lines, AUTO_END_MARKER]).rstrip() + "\n"


def merge_autogenerated(existing: str, generated_block: str, full_document: str) -> str:
    if AUTO_START_MARKER not in existing or AUTO_END_MARKER not in existing:
        return full_document

    pattern = re.compile(
        rf"{re.escape(AUTO_START_MARKER)}.*?{re.escape(AUTO_END_MARKER)}\n?",
        re.DOTALL,
    )
    return pattern.sub(generated_block, existing, count=1)


def render_document(title: str, preface: str, generated_lines: list[str]) -> str:
    generated_block = render_generated_block(generated_lines)
    return f"# {title}\n\n{preface}\n\n{generated_block}"


def _bullet_lines(items: list[str], empty_fallback: str) -> list[str]:
    if not items:
        return [f"- {empty_fallback}"]
    return [f"- {item}" for item in items]


def build_overview_doc(metadata: ProjectMetadata, server_url: str) -> str:
    source_uri = f"`viking://resources/projects/{metadata.slug}/source`"
    docs_uri = f"`viking://resources/projects/{metadata.slug}/docs`"
    context_uri = f"`viking://resources/projects/{metadata.slug}/context`"
    generated_lines = [
        f"Generated at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Snapshot",
        f"- Project name: `{metadata.project_name}`",
        f"- Project root: `{metadata.project_root}`",
        f"- OpenViking slug: `{metadata.slug}`",
        f"- Summary: {metadata.description}",
        f"- Python requirement: `{metadata.python_requirement or 'not declared'}`",
        "",
        "## Tech Stack",
        *_bullet_lines(metadata.tech_stack, "Capture the core stack here."),
        "",
        "## Entry Points",
        "- Start commands:",
        *_bullet_lines([f"`{command}`" for command in metadata.run_commands], "Document how to start the app."),
        "- Test commands:",
        *_bullet_lines([f"`{command}`" for command in metadata.test_commands], "Document the primary validation command."),
        "",
        "## Repository Layout",
        *_bullet_lines(metadata.top_level_layout, "Summarize the top-level modules."),
        "",
        "## Key Documents",
        *_bullet_lines([f"`{doc}`" for doc in metadata.selected_docs], "List the highest-signal docs to retrieve first."),
        "",
        "## OpenViking Retrieval Targets",
        f"- Source namespace: {source_uri}",
        f"- Docs namespace: {docs_uri}",
        f"- Context namespace: {context_uri}",
        f"- Server health endpoint: `{server_url.rstrip('/')}/health`",
    ]
    return render_document(
        "Overview",
        "Use this as the first retrieval target before asking Codex or Cursor to edit code. Keep any manual notes outside the auto-generated block.",
        generated_lines,
    )


def build_decisions_doc(metadata: ProjectMetadata) -> str:
    inferred_decisions: list[str] = []
    if metadata.python_requirement:
        inferred_decisions.append(f"Python runtime baseline appears to be `{metadata.python_requirement}`.")
    if metadata.tech_stack:
        inferred_decisions.extend(metadata.tech_stack)
    if "`rag_core/`" in metadata.top_level_layout and "`rag_ui/`" in metadata.top_level_layout:
        inferred_decisions.append("Repository layout separates core RAG logic from UI-facing code.")

    generated_lines = [
        f"Generated at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Inferred Decisions To Verify",
        *_bullet_lines(inferred_decisions, "Replace this with explicit architectural decisions from the team."),
        "",
        "## Decision Recording Rule",
        "- Capture only durable choices that affect future implementation or operations.",
        "- For each decision, record the context, the chosen option, and the consequence.",
        "- Remove inferred placeholders once they are confirmed by maintainers.",
        "",
        "## Pending Decisions",
        "- Add the next architectural or workflow decision here after each significant change.",
    ]
    return render_document(
        "Decisions",
        "Record durable technical decisions here. This file starts with inferred entries so the first onboarding run is useful, but those entries should be confirmed and edited.",
        generated_lines,
    )


def build_runbook_doc(
    metadata: ProjectMetadata,
    rerun_command: str,
    server_url: str,
) -> str:
    generated_lines = [
        f"Generated at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Preconditions",
        f"- OpenViking server should be reachable at `{server_url}`.",
        "- If your OpenViking embedding backend points to a local model server such as Ollama, ensure that backend is already running before a full import.",
        "- Project-local dependencies still need to be installed according to the project's own setup guide.",
        "",
        "## Start Project",
        *_bullet_lines([f"`{command}`" for command in metadata.run_commands], "Add the primary startup command."),
        "",
        "## Validate Project",
        *_bullet_lines([f"`{command}`" for command in metadata.test_commands], "Add the primary validation command."),
        "",
        "## Refresh OpenViking Context",
        f"- Re-run onboarding: `{rerun_command}`",
        f"- Check OpenViking health: `curl -s {shlex.quote(server_url.rstrip('/') + '/health')}`",
        "",
        "## Resource Namespaces",
        f"- `viking://resources/projects/{metadata.slug}/source`",
        f"- `viking://resources/projects/{metadata.slug}/docs`",
        f"- `viking://resources/projects/{metadata.slug}/context`",
    ]
    return render_document(
        "Runbook",
        "Keep operational commands here. Update this file whenever startup, test, or recovery steps change.",
        generated_lines,
    )


def build_current_focus_doc(metadata: ProjectMetadata) -> str:
    generated_lines = [
        f"Generated at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Current Objective",
        "- Replace this line with the active delivery goal before starting a new task.",
        "",
        "## High-Signal Docs To Review",
        *_bullet_lines([f"`{doc}`" for doc in metadata.focus_docs], "Point to the plans, runbooks, or recent fixes that matter right now."),
        "",
        "## Known Risks Or Blockers",
        "- Add the current blocker list here and keep it short.",
        "",
        "## Next Update Rule",
        "- After each completed task, refresh this file with the new objective, blockers, and next high-value step.",
    ]
    return render_document(
        "Current Focus",
        "This file is intentionally short. It should change often and reflect the current iteration state more than long-term architecture.",
        generated_lines,
    )


def build_workflow_doc(metadata: ProjectMetadata, rerun_command: str) -> str:
    context_uri = f"`viking://resources/projects/{metadata.slug}/context`"
    source_uri = f"`viking://resources/projects/{metadata.slug}/source`"
    docs_uri = f"`viking://resources/projects/{metadata.slug}/docs`"
    generated_lines = [
        f"Generated at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Fixed Workflow",
        "1. Retrieve first.",
        f"   Read `overview.md`, `current-focus.md`, and `runbook.md` from {context_uri}.",
        f"   Search {source_uri} and {docs_uri} before proposing edits.",
        "2. Implement second.",
        "   Restrict changes to the files supported by the retrieved context and run the smallest relevant validation.",
        "3. Write back conclusions.",
        "   Update `decisions.md` for durable changes, `current-focus.md` for iteration state, and `runbook.md` if operating steps changed.",
        f"   Re-run onboarding with `{rerun_command}` so OpenViking indexes the refreshed context pack.",
        "",
        "## Codex Kickoff Prompt",
        f"- Start by retrieving the relevant context from {context_uri}, then search {source_uri} and {docs_uri}, then implement, test, and write back decisions or runbook changes before finishing.",
        "",
        "## Cursor Kickoff Prompt",
        f"- Before editing, retrieve the project context from {context_uri}; use the retrieved docs to narrow the target files, then update the context files when the task changes behavior, decisions, or operations.",
    ]
    return render_document(
        "Codex Cursor Workflow",
        "This is the operating contract for agent work on this repository: retrieve first, code second, write back third.",
        generated_lines,
    )


def write_context_doc(path: Path, content: str) -> None:
    existing = safe_read_text(path, max_chars=200_000)
    generated_block = render_generated_block(
        content.split(AUTO_START_MARKER, 1)[1].split(AUTO_END_MARKER, 1)[0].strip().splitlines()
    )
    final_content = merge_autogenerated(existing, generated_block, content) if existing else content
    path.write_text(final_content, encoding="utf-8")


def ensure_context_documents(
    project_root: Path,
    metadata: ProjectMetadata,
    rerun_command: str,
    server_url: str,
) -> dict[str, Path]:
    context_dir = project_root / CONTEXT_RELATIVE_DIR
    context_dir.mkdir(parents=True, exist_ok=True)

    docs = {
        "overview.md": build_overview_doc(metadata, server_url),
        "decisions.md": build_decisions_doc(metadata),
        "runbook.md": build_runbook_doc(metadata, rerun_command, server_url),
        "current-focus.md": build_current_focus_doc(metadata),
        "codex-cursor-workflow.md": build_workflow_doc(metadata, rerun_command),
    }

    written: dict[str, Path] = {}
    for filename, content in docs.items():
        path = context_dir / filename
        write_context_doc(path, content)
        written[filename] = path
    return written


def build_manifest(
    metadata: ProjectMetadata,
    server_url: str,
    rerun_command: str,
    context_docs: dict[str, Path],
    import_specs: list[ImportSpec],
    import_results: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_name": metadata.project_name,
        "project_slug": metadata.slug,
        "project_root": str(metadata.project_root),
        "server_url": server_url,
        "rerun_command": rerun_command,
        "context_dir": str(metadata.project_root / CONTEXT_RELATIVE_DIR),
        "context_docs": {name: str(path) for name, path in context_docs.items()},
        "selected_docs": metadata.selected_docs,
        "focus_docs": metadata.focus_docs,
        "import_specs": [spec.to_manifest() for spec in import_specs],
        "imports": import_results,
    }


def write_manifest(context_dir: Path, manifest: dict[str, object]) -> Path:
    manifest_path = context_dir / "onboarding-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def resolve_local_config_path() -> Path | None:
    env_value = os.environ.get(OPENVIKING_CONFIG_ENV)
    if env_value:
        candidate = Path(env_value).expanduser()
        if candidate.exists():
            return candidate.resolve()
    if USER_DEFAULT_CONFIG.exists():
        return USER_DEFAULT_CONFIG.resolve()
    if REPO_DEFAULT_CONFIG.exists():
        return REPO_DEFAULT_CONFIG.resolve()
    return None


def detect_local_ollama_api_base() -> str | None:
    config_path = resolve_local_config_path()
    if config_path is None:
        return None

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    dense_config = payload.get("embedding", {}).get("dense", {})
    if not isinstance(dense_config, dict):
        return None

    provider = str(dense_config.get("provider", "")).strip().lower()
    api_base = str(dense_config.get("api_base", "")).strip()
    if provider != "ollama" and "11434" not in api_base:
        return None
    if api_base.endswith("/v1"):
        api_base = api_base[:-3]
    return api_base.rstrip("/")


def preflight_local_backend(wait: bool) -> str | None:
    api_base = detect_local_ollama_api_base()
    if not api_base:
        return None

    try:
        response = requests.get(f"{api_base}/api/tags", timeout=2)
        if response.status_code == 200:
            return f"Verified local Ollama backend at {api_base}."
    except requests.RequestException:
        pass

    message = (
        f"Configured local Ollama backend is not reachable at {api_base}. "
        "Start the backend before running onboarding in wait mode."
    )
    if wait:
        raise OnboardError(message)
    return message + " Imports will be queued without waiting."


def server_healthy(server_url: str) -> bool:
    try:
        response = requests.get(f"{server_url.rstrip('/')}/health", timeout=2)
    except requests.RequestException:
        return False
    if response.status_code != 200:
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    return bool(payload.get("healthy", True))


def ensure_server(server_url: str, *, skip_server_start: bool) -> bool:
    if server_healthy(server_url):
        return False
    if skip_server_start:
        raise OnboardError(f"OpenViking server is not healthy at {server_url}.")

    launcher = REPO_ROOT / "scripts" / "openviking_start.py"
    process = subprocess.Popen(
        [str(launcher)],
        cwd=str(REPO_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    deadline = time.time() + 60
    while time.time() < deadline:
        if server_healthy(server_url):
            return True
        if process.poll() is not None:
            raise OnboardError("OpenViking launcher exited before the server became healthy.")
        time.sleep(1)

    raise OnboardError(f"Timed out waiting for OpenViking server at {server_url}.")


def import_resource(server_url: str, spec: ImportSpec) -> dict[str, object]:
    if not spec.path.exists():
        raise OnboardError(f"Import path does not exist for `{spec.name}`: {spec.path}")

    timeout = (spec.timeout or 60.0) + 15.0 if spec.wait else 60.0
    try:
        response = requests.post(
            f"{server_url.rstrip('/')}/api/v1/resources",
            json=spec.to_payload(),
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise OnboardError(f"Failed to import `{spec.name}` into OpenViking: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise OnboardError(f"OpenViking returned a non-JSON response for `{spec.name}`.") from exc

    if payload.get("status") != "ok":
        raise OnboardError(f"OpenViking import for `{spec.name}` returned status `{payload.get('status')}`.")

    result = payload.get("result") or {}
    return {
        "name": spec.name,
        "path": str(spec.path),
        "to_uri": spec.to_uri,
        "root_uri": result.get("root_uri"),
        "status": result.get("status", "ok"),
        "errors": result.get("errors", []),
    }


def validate_project_root(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise OnboardError(f"Project path does not exist: {resolved}")
    if not resolved.is_dir():
        raise OnboardError(f"Project path is not a directory: {resolved}")
    return resolved


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate and import an OpenViking project context pack.")
    parser.add_argument("-path", "--path", dest="project_path", required=True, help="Absolute path to the target project.")
    parser.add_argument("--project-name", help="Override the project name used in generated docs and URIs.")
    parser.add_argument("--server-url", default=DEFAULT_SERVER_URL, help=f"OpenViking base URL. Default: {DEFAULT_SERVER_URL}")
    parser.add_argument(
        "--wait",
        dest="wait",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Wait for OpenViking to finish each import before returning.",
    )
    parser.add_argument("--timeout", type=float, default=600.0, help="Per-import timeout in seconds when --wait is enabled.")
    parser.add_argument("--dry-run", action="store_true", help="Generate docs and manifest only; skip server startup and imports.")
    parser.add_argument("--skip-server-start", action="store_true", help="Require the OpenViking server to already be running.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        project_root = validate_project_root(Path(args.project_path))
        project_name = args.project_name or project_root.name
        slug = slugify(project_name)
        rerun_command = f"{REPO_ROOT / 'script.sh'} -path {shlex.quote(str(project_root))}"
        metadata = collect_project_metadata(project_root, project_name, slug)
        context_docs = ensure_context_documents(project_root, metadata, rerun_command, args.server_url)
        import_specs = build_import_specs(
            project_root,
            slug,
            project_root / CONTEXT_RELATIVE_DIR,
            wait=args.wait,
            timeout=args.timeout,
        )

        manifest = build_manifest(metadata, args.server_url, rerun_command, context_docs, import_specs, [])
        manifest_path = write_manifest(project_root / CONTEXT_RELATIVE_DIR, manifest)

        started_server = False
        backend_note = None
        import_results: list[dict[str, object]] = []
        if not args.dry_run:
            backend_note = preflight_local_backend(args.wait)
            started_server = ensure_server(args.server_url, skip_server_start=args.skip_server_start)
            for spec in import_specs:
                import_results.append(import_resource(args.server_url, spec))

            manifest = build_manifest(
                metadata,
                args.server_url,
                rerun_command,
                context_docs,
                import_specs,
                import_results,
            )
            manifest_path = write_manifest(project_root / CONTEXT_RELATIVE_DIR, manifest)

        summary = {
            "project_name": metadata.project_name,
            "project_slug": metadata.slug,
            "project_root": str(project_root),
            "context_dir": str(project_root / CONTEXT_RELATIVE_DIR),
            "context_docs": {name: str(path) for name, path in context_docs.items()},
            "manifest_path": str(manifest_path),
            "selected_docs": metadata.selected_docs,
            "import_targets": [spec.to_manifest() for spec in import_specs],
            "imports": import_results,
            "started_server": started_server,
            "backend_note": backend_note,
            "dry_run": args.dry_run,
            "rerun_command": rerun_command,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except OnboardError as exc:
        print(f"[openviking-onboard] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
