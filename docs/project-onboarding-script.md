# Project Onboarding Script

`script.sh` turns an existing repository into an OpenViking-managed workspace in one flow:

1. Inspect the project root and infer the most useful startup, test, and documentation context.
2. Generate `.openviking/context/overview.md`, `decisions.md`, `runbook.md`, `current-focus.md`, and `codex-cursor-workflow.md`.
3. Start the local OpenViking server when needed.
4. Import source, curated docs, and generated context into `viking://resources/projects/<slug>/...`.

## Usage

```bash
./script.sh -path /absolute/path/to/project
```

Optional flags:

```bash
./script.sh -path /absolute/path/to/project --dry-run
./script.sh -path /absolute/path/to/project --project-name rag-demo-v2.6.0-clean
./script.sh -path /absolute/path/to/project --server-url http://127.0.0.1:1933
./script.sh -path /absolute/path/to/project --no-wait
```

## What Gets Imported

- `source`: project root with noisy directories excluded, including top-level guides such as `README`, `AGENTS.md`, and runbooks.
- `docs`: curated documentation from `docs/`, filtered toward text-heavy files and away from images or exported HTML.
- `context`: generated files under `.openviking/context/`.

## Generated Context Files

- `overview.md`: project summary, stack, layout, key docs, and OpenViking namespaces.
- `decisions.md`: inferred architectural decisions that should be confirmed and maintained.
- `runbook.md`: startup, validation, and context refresh commands.
- `current-focus.md`: short-lived iteration state and blockers.
- `codex-cursor-workflow.md`: fixed agent workflow of retrieve first, code second, write back third.

## Operational Notes

- The script preserves manual notes outside the `AUTO-GENERATED` block in each context file.
- Imports are idempotent because the tool always targets the same `viking://resources/projects/<slug>/...` URIs.
- Full `--wait` imports depend on your OpenViking embedding backend being available. If your config points to a local Ollama instance, start that backend before running the script for a complete indexed import.
