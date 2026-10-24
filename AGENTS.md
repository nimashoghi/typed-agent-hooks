# Agent guidance for typed-agent-hooks

This repository is a standalone uv-managed Python package.

Use `uv run ...` for repository commands. The standard checks are:

- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run ty check`
- `uv run pytest -q`

Keep Codex and Claude Code wire schemas explicit and separate. Wire inputs are tolerant readers: unknown host fields are ignored, declared fields stay strictly typed. Outputs stay closed and exact. Shared behavior stays conservative: unsupported host behavior fails loudly instead of being silently normalized.

A hook is one executable PEP 723 file that registers handlers on `shared.HookApp` and calls `app.main()`. Hook files hold only logic. The host files (`.codex/hooks.json`, `.claude/settings.json`) hold the event, matcher, timeout and command, and pass the host name as the only argument. Do not add host configuration generation, installation, manifests, or import-string loaders to this package.
