# typed-agent-hooks

`typed-agent-hooks` gives OpenAI Codex and Anthropic Claude Code hooks one set of typed events. A hook file handles shared events, such as `ToolCallCompleted`. The package parses the host payload, maps it to the shared event, calls the handler, and writes the output in the format of that host. A hook file never names a host.

The host files hold the native event, matcher, timeout and command. The package does not generate or install host configuration.

## A hook file

Each hook is one executable PEP 723 file:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["typed-agent-hooks==0.3.0"]
# [tool.uv]
# exclude-newer = "2026-11-01T00:00:00Z"
# ///
"""Suggest the notebook when a Bash command runs inline Python."""

from typed_agent_hooks import shared

app = shared.HookApp(name="inline-python")


@app.on(shared.events.ToolCallCompleted)
def tool_completed(event: shared.events.ToolCallCompleted) -> shared.outputs.Result:
    command = event.tool_input.get("command") if isinstance(event.tool_input, dict) else None
    if not isinstance(command, str) or "python -c" not in command:
        return None
    return shared.outputs.AddContext(text="For multi-step Python work, use the notebook.")


if __name__ == "__main__":
    app.main()
```

Set `exclude-newer` to a date after the release that the file pins, because uv ignores releases that are newer than that date.

## Host files

The host files call the hook with the host name as the only argument. Codex, in `.codex/hooks.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{ "type": "command", "command": ".agent-hooks/inline-python.py codex", "timeout": 5 }]
      }
    ]
  }
}
```

Claude Code, in `.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "\"$CLAUDE_PROJECT_DIR\"/.agent-hooks/inline-python.py claude",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

## What `main()` does

`app.main()` reads the host from its first argument (`codex` or `claude`) and the payload from stdin. The payload's `hook_event_name` selects the event. `main()` calls the handler of that event and writes the host output to stdout.

- A handler that returns `None` writes nothing.
- A failure fails open: one line on stderr, nothing on stdout, exit 0. Failures include a payload that does not parse, an event that has no handler, an event that has no shared equivalent, a handler exception, and an output that the event cannot carry.
- A missing or unknown host argument is a programming error: a usage line on stderr and exit 1. Both hosts read exit 1 as a non-blocking error, so a wrong host file does not block a tool call or a prompt.

`app.handle(host, payload)` does the same work in the current process and raises on each failure. Use it in tests.

## Check host files without a host

A test can load a hook file without running it and compare its events with the host files:

```python
import runpy

from typed_agent_hooks import shared

app = runpy.run_path(".agent-hooks/inline-python.py")["app"]
for event_type in app.handlers:
    print(shared.native_event_name(event_type, "codex"), shared.native_event_name(event_type, "claude"))
```

`app.handlers` maps each shared event type to its handler. `shared.native_event_name(event_type, host)` returns the native event name, or `None` when the host has no such event.

## Shared events

| Shared event (`shared.events`) | Codex | Claude Code | `AddContext` |
| --- | --- | --- | --- |
| `SessionStarted` | `SessionStart` | `SessionStart` | yes |
| `PromptSubmitted` | `UserPromptSubmit` | `UserPromptSubmit` | yes |
| `ToolCallProposed` | `PreToolUse` | `PreToolUse` | yes |
| `PermissionRequested` | `PermissionRequest` | `PermissionRequest` | no |
| `ToolCallCompleted` | `PostToolUse` | `PostToolUse` | yes |
| `ToolCallFailed` | none | `PostToolUseFailure` | no |
| `CompactionStarting` | `PreCompact` | `PreCompact` | no |
| `CompactionFinished` | `PostCompact` | `PostCompact` | no |
| `SubagentStarted` | `SubagentStart` | `SubagentStart` | yes |
| `SubagentStopped` | `SubagentStop` | `SubagentStop` | no |
| `TurnStopped` | `Stop` | `Stop` | no |

Every event carries `event.context` with the host, session ID, working directory and other session data. A handler returns one of the results in `shared.outputs`: `AddContext`, `SystemMessage`, `Block`, `AllowTool`, `DenyTool`, `AllowPermission`, `DenyPermission`, `Stop`, or `None`. A result that an event cannot carry raises `SharedOutputError`. The package does not guess a translation.

## Host wire schemas

`typed_agent_hooks.codex` and `typed_agent_hooks.claude_code` hold the native schemas of each host. Wire inputs ignore unknown fields, but declared fields stay strictly typed. Outputs are closed and exact.

## Development

```console
uv run ruff check .
uv run ty check
uv run pytest -q
```
