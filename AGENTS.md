# Agent guidance for typed-agent-hooks

This repository is a standalone uv-managed Python package.

Use `uv run ...` for repository commands. The standard checks are:

- `uv run ruff check .`
- `uv run ty check`
- `uv run pytest -q`

Keep Codex and Claude Code wire schemas explicit and separate. Shared-mode
behavior should stay conservative: unsupported provider behavior should fail
loudly instead of being silently normalized.
