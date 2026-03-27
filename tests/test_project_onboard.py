from __future__ import annotations

import json
from pathlib import Path

from scripts.project_onboard import (
    AUTO_END_MARKER,
    AUTO_START_MARKER,
    CONTEXT_RELATIVE_DIR,
    build_import_specs,
    build_manifest,
    collect_project_metadata,
    ensure_context_documents,
    slugify,
    write_manifest,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_demo_project(project_root: Path) -> None:
    _write(
        project_root / "pyproject.toml",
        """
[project]
name = "rag-demo"
version = "3.0.0"
description = "Clean local RAG demo for testing."
requires-python = ">=3.12"
dependencies = [
  "streamlit>=1.0.0",
  "langchain>=0.0.1",
  "langchain-ollama>=0.0.1",
  "chromadb>=0.5.0",
]
""".strip(),
    )
    _write(project_root / "Readme.md", "# Demo\n\nLocal RAG demo project.\n")
    _write(project_root / "RUNNING_GUIDE.md", "# Running\n\nUse python scripts/start.py.\n")
    _write(project_root / "requirements.txt", "streamlit\nlangchain\n")
    _write(project_root / "scripts" / "start.py", "print('start')\n")
    _write(project_root / "tests" / "test_smoke.py", "def test_smoke():\n    assert True\n")
    _write(project_root / "rag_core" / "__init__.py", "")
    _write(project_root / "rag_ui" / "__init__.py", "")
    _write(project_root / "docs" / "technical" / "architecture.md", "# Architecture\n\nDetails.\n")
    _write(project_root / "docs" / "workflows" / "release.md", "# Release\n\nChecklist.\n")


def test_slugify_normalizes_project_names() -> None:
    assert slugify("rag-demo-v2.6.0 clean") == "rag-demo-v2-6-0-clean"
    assert slugify("  Demo__Project  ") == "demo-project"


def test_build_import_specs_includes_source_docs_and_context(tmp_path: Path) -> None:
    project_root = tmp_path / "rag-demo"
    _make_demo_project(project_root)
    context_dir = project_root / CONTEXT_RELATIVE_DIR
    context_dir.mkdir(parents=True)

    specs = build_import_specs(project_root, "rag-demo", context_dir, wait=True, timeout=123.0)

    assert [spec.name for spec in specs] == ["source", "docs", "context"]
    assert specs[0].path == project_root
    assert specs[1].path == project_root / "docs"
    assert specs[2].path == context_dir
    assert specs[1].include == "*.md,*.mdx,*.rst,*.txt,*.yaml,*.yml,*.json,*.toml,*.pdf"
    assert specs[0].exclude is not None
    assert all(spec.wait for spec in specs)


def test_ensure_context_documents_creates_expected_files(tmp_path: Path) -> None:
    project_root = tmp_path / "rag-demo"
    _make_demo_project(project_root)
    metadata = collect_project_metadata(project_root, "rag-demo", "rag-demo")
    assert "requirements.txt" not in metadata.selected_docs

    context_docs = ensure_context_documents(
        project_root,
        metadata,
        "/tmp/openviking/script.sh -path /tmp/rag-demo",
        "http://127.0.0.1:1933",
    )

    assert set(context_docs) == {
        "overview.md",
        "decisions.md",
        "runbook.md",
        "current-focus.md",
        "codex-cursor-workflow.md",
    }

    overview_text = (project_root / CONTEXT_RELATIVE_DIR / "overview.md").read_text(encoding="utf-8")
    workflow_text = (project_root / CONTEXT_RELATIVE_DIR / "codex-cursor-workflow.md").read_text(encoding="utf-8")
    assert "viking://resources/projects/rag-demo/source" in overview_text
    assert "retrieve first, code second, write back third" in workflow_text.lower()


def test_ensure_context_documents_preserves_manual_notes(tmp_path: Path) -> None:
    project_root = tmp_path / "rag-demo"
    _make_demo_project(project_root)
    metadata = collect_project_metadata(project_root, "rag-demo", "rag-demo")
    context_dir = project_root / CONTEXT_RELATIVE_DIR
    context_dir.mkdir(parents=True, exist_ok=True)
    overview_path = context_dir / "overview.md"
    overview_path.write_text(
        "\n".join(
            [
                "# Overview",
                "",
                "Manual note above.",
                "",
                AUTO_START_MARKER,
                "old generated content",
                AUTO_END_MARKER,
                "",
                "Manual note below.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    ensure_context_documents(
        project_root,
        metadata,
        "/tmp/openviking/script.sh -path /tmp/rag-demo",
        "http://127.0.0.1:1933",
    )

    updated_text = overview_path.read_text(encoding="utf-8")
    assert "Manual note above." in updated_text
    assert "Manual note below." in updated_text
    assert "old generated content" not in updated_text
    assert "viking://resources/projects/rag-demo/source" in updated_text


def test_build_and_write_manifest_records_imports(tmp_path: Path) -> None:
    project_root = tmp_path / "rag-demo"
    _make_demo_project(project_root)
    metadata = collect_project_metadata(project_root, "rag-demo", "rag-demo")
    context_docs = ensure_context_documents(
        project_root,
        metadata,
        "/tmp/openviking/script.sh -path /tmp/rag-demo",
        "http://127.0.0.1:1933",
    )
    specs = build_import_specs(
        project_root,
        "rag-demo",
        project_root / CONTEXT_RELATIVE_DIR,
        wait=False,
        timeout=45.0,
    )
    manifest = build_manifest(
        metadata,
        "http://127.0.0.1:1933",
        "/tmp/openviking/script.sh -path /tmp/rag-demo",
        context_docs,
        specs,
        [{"name": "source", "status": "ok"}],
    )

    manifest_path = write_manifest(project_root / CONTEXT_RELATIVE_DIR, manifest)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert payload["project_slug"] == "rag-demo"
    assert payload["imports"] == [{"name": "source", "status": "ok"}]
    assert payload["import_specs"][0]["name"] == "source"
    assert "*.code-workspace" in payload["import_specs"][0]["exclude"]
