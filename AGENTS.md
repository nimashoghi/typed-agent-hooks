# Agent guidance for typed-agent-hooks

This repository is a standalone uv-managed Python package.

Use `uv run ...` for repository commands. The standard checks are:

- `uv run ruff check .`
- `uv run ty check`
- `uv run pytest -q`

Keep Codex and Claude Code wire schemas explicit and separate. Wire inputs are
tolerant readers: unknown provider fields are ignored, declared fields stay
strictly typed. Outputs stay closed and exact. Shared-mode behavior should stay
conservative: unsupported provider behavior should fail loudly instead of being
silently normalized.
