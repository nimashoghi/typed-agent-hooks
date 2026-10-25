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
# exclude-newer = "2026-10-25T00:00:00Z"
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

uv uses only uploads from before the `exclude-newer` date, for every package. Set the date on or after the upload date of the pinned `typed-agent-hooks` release, or uv cannot find that release. The date also freezes the other dependencies.

## Host files

The host files call the hook with the host name as the only argument. The command ends with `|| true`, so that a failure before `main()` runs cannot block the action (see below). Codex, in `.codex/hooks.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{ "type": "command", "command": ".agent-hooks/inline-python.py codex || true", "timeout": 5 }]
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
            "command": "\"$CLAUDE_PROJECT_DIR\"/.agent-hooks/inline-python.py claude || true",
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

- A handler that returns `None` writes nothing. Everything else that the process writes to stdout (a `print` at import or in a handler, a child process, a C library) goes to stderr, so stdout holds only the host output. Text that Python wrote to stdout before `main()` runs and without a buffer (`python -u` or `PYTHONUNBUFFERED`) cannot be recalled.
- A failure fails open: one line on stderr, nothing on stdout, exit 0. Failures include a payload that does not parse, an event that has no handler, an event that has no shared equivalent, a handler exception or `sys.exit`, and an output that the event cannot carry.
- A missing or unknown host argument is a programming error: a usage line on stderr and exit 1. Both hosts read exit 1 as a non-blocking error, so a wrong host file does not block a tool call or a prompt.

`main()` fails open only after the file runs. `uv run --script` can fail before that, for example when the uv cache is cold and the package index is not available. uv then exits 2, which both hosts read as a blocking error. The `|| true` in the host command turns that exit into 0. `main()` reports every block and deny decision as JSON with exit 0, so no intended behavior depends on the exit code.

`app.handle(host, payload)` does the same work in the current process and raises on each failure. Use it in tests.

## Check host files without a host

A test can load a hook file without running it and compare its events with the host files:

```python
import runpy
import sys

from typed_agent_hooks import shared

sys.path.insert(0, ".agent-hooks")  # for helper modules next to the hooks
app = runpy.run_path(".agent-hooks/inline-python.py")["app"]
for event_type in app.handlers:
    print(shared.native_event_name(event_type, "codex"), shared.native_event_name(event_type, "claude"))
```

`app.handlers` maps each shared event type to its handler. `shared.native_event_name(event_type, host)` returns the native event name, or `None` when the host has no such event. Codex has no `ToolCallFailed` event: Claude Code sends a failed tool call as `PostToolUseFailure`, and Codex sends it as `PostToolUse`. A hook that must see every finished tool call in both hosts handles `ToolCallCompleted` and `ToolCallFailed`.

## Shared events

| Shared event (`shared.events`) | Codex | Claude Code | `AddContext` |
| --- | --- | --- | --- |
| `SessionStarted` | `SessionStart` | `SessionStart` | yes |
| `PromptSubmitted` | `UserPromptSubmit` | `UserPromptSubmit` | yes |
| `ToolCallProposed` | `PreToolUse` | `PreToolUse` | yes |
| `PermissionRequested` | `PermissionRequest` | `PermissionRequest` | no |
| `ToolCallCompleted` | `PostToolUse` | `PostToolUse` | yes |
| `ToolCallFailed` | none | `PostToolUseFailure` | yes |
| `CompactionStarting` | `PreCompact` | `PreCompact` | no |
| `CompactionFinished` | `PostCompact` | `PostCompact` | no |
| `SubagentStarted` | `SubagentStart` | `SubagentStart` | yes |
| `SubagentStopped` | `SubagentStop` | `SubagentStop` | no |
| `TurnStopped` | `Stop` | `Stop` | no |

Every event carries `event.context` with the host, session ID, working directory and other session data. A handler returns one of the results in `shared.outputs`: `AddContext`, `SystemMessage`, `Block`, `AllowTool`, `DenyTool`, `AllowPermission`, `DenyPermission`, `Stop`, or `None`. A result that an event cannot carry in both hosts raises `SharedOutputError`. The package does not guess a translation. The compaction events accept no result: Claude Code ignores `systemMessage` and `continue` on them, and a block means different things in the two hosts. `AllowTool` differs by host: Claude Code skips its permission prompt (and applies `updated_input` when it is set), while Codex only applies `updated_input` and its normal approval still runs. Codex rejects an allow without `updated_input`, so that result raises for Codex. `Stop` is valid only on `PromptSubmitted`, `SubagentStopped` and `TurnStopped`: Claude Code has no decision control on `SessionStart`, and Codex turns a stop on `PostToolUse` into model feedback and continues the turn.

## Host wire schemas

`typed_agent_hooks.codex` and `typed_agent_hooks.claude_code` hold the native schemas of each host, for the events in the table above. An input model declares only the fields that the shared events read. It ignores other fields, so a host change to a field that no hook reads cannot break a hook. Declared fields stay strictly typed. An output model holds only the fields that the shared results write, and it is closed and exact. A Claude Code event with no shared equivalent, such as `Notification`, is not modeled: `parse_input` raises `ValueError`, and `main()` fails open.

## Development

```console
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest -q
```
