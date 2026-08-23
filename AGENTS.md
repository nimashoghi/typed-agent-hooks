# Agent guidance for typed-agent-hooks

This repository is a standalone uv-managed Python package.

Use `uv run ...` for repository commands. The standard checks are:

- `uv run ruff check .`
- `uv run ty check`
- `uv run pytest -q`

Keep Codex and Claude Code wire schemas explicit and separate. Wire inputs are tolerant readers: unknown provider fields are ignored, declared fields stay strictly typed. Outputs stay closed and exact. Shared behavior stays conservative: unsupported provider behavior fails loudly instead of being silently normalized.

Hook applications are code-first executable PEP 723 files. Configuration lives on `HookApp` and its decorators. Do not add manifests, import-string loaders, or a global installation CLI. Public CLIs use direct Cyclopts views of the same documented functions callers import from Python. Private child-process protocol code may parse its own arguments because it is not a user API.
