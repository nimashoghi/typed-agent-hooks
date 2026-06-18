# typed-agent-hooks

Strict, explicit Python APIs and managed hooksets for **OpenAI Codex** and **Anthropic Claude Code** command hooks.

The package has three deliberately separate modes:

```text
typed_agent_hooks.codex        # Codex wire events and outputs
typed_agent_hooks.claude_code  # Claude Code wire events and outputs
typed_agent_hooks.shared       # explicit semantic intersection
```

There is no provider auto-detection and no implicit normalization. You choose the mode in Python, in `hookset.toml`, and at the CLI boundary.

## Design principles

- Provider wire schemas remain authoritative and separate.
- All Pydantic models use strict validation and reject unknown fields.
- Python attributes use `snake_case`; provider JSON aliases are emitted at the wire boundary.
- Handler registration uses concrete event model classes, not untyped strings.
- A handler may return only the exact output model for its event.
- Shared mode uses explicit semantic events and explicit portable result types.
- Unsupported shared behavior fails loudly instead of being silently discarded.
- Hookset installation is atomic, idempotent, and preserves unrelated configuration.

## Install

```bash
pip install typed-agent-hooks
```

Python 3.10 or newer is required.

## Start a hook project

Shared mode:

```bash
typed-agent-hooks init .agent-hooks --mode shared
```

Provider-specific modes:

```bash
typed-agent-hooks init .agent-hooks-codex --mode codex
typed-agent-hooks init .agent-hooks-claude --mode claude-code
```

The command creates:

```text
.agent-hooks/
  hooks.py
  hookset.toml
  README.md
```

## Provider-specific applications

### Codex

```python
from __future__ import annotations

from typed_agent_hooks import codex

app = codex.HookApp()


@app.on(codex.events.UserPromptSubmitInput)
def inspect_prompt(
    event: codex.events.UserPromptSubmitInput,
) -> codex.outputs.HookResult:
    if "AWS_SECRET_ACCESS_KEY" not in event.prompt:
        return None
    return codex.outputs.UserPromptSubmitOutput(
        decision="block",
        reason="Remove secrets before submitting this prompt.",
    )
```

### Claude Code

```python
from __future__ import annotations

from typed_agent_hooks import claude_code

app = claude_code.HookApp()


@app.on(claude_code.events.PreToolUseInput)
def inspect_tool(
    event: claude_code.events.PreToolUseInput,
) -> claude_code.outputs.HookResult:
    if event.tool_name != "Bash" or not isinstance(event.tool_input, dict):
        return None
    command = event.tool_input.get("command")
    if not isinstance(command, str) or "rm -rf /" not in command:
        return None
    return claude_code.outputs.PreToolUseOutput(
        hook_specific_output=claude_code.outputs.PreToolUseSpecificOutput(
            hook_event_name="PreToolUse",
            permission_decision="deny",
            permission_decision_reason="Refusing destructive root command.",
        )
    )
```

Passing the event class to `app.on(...)` ties the decorator to the concrete handler parameter type. It also avoids runtime inference from annotations or event-name strings.

## Explicit shared mode

Shared mode maps a conservative semantic event set from both providers:

| Shared event | Codex primitive | Claude Code primitive |
|---|---|---|
| `SessionStarted` | `SessionStart` | `SessionStart` |
| `PromptSubmitted` | `UserPromptSubmit` | `UserPromptSubmit` |
| `ToolCallProposed` | `PreToolUse` | `PreToolUse` |
| `PermissionRequested` | `PermissionRequest` | `PermissionRequest` |
| `ToolCallCompleted` | `PostToolUse` | `PostToolUse` |
| `CompactionStarting` | `PreCompact` | `PreCompact` |
| `CompactionFinished` | `PostCompact` | `PostCompact` |
| `SubagentStarted` | `SubagentStart` | `SubagentStart` |
| `SubagentStopped` | `SubagentStop` | `SubagentStop` |
| `TurnStopped` | `Stop` | `Stop` |

Claude-only events do not get coerced into this layer. `shared.try_from_claude_code(...)` returns `None`; `shared.from_claude_code(...)` raises `NoSharedMappingError`.

```python
from __future__ import annotations

from typed_agent_hooks import shared

app = shared.HookApp()


@app.on(shared.events.PromptSubmitted)
def inspect_prompt(
    event: shared.events.PromptSubmitted,
) -> shared.outputs.Result:
    if "AWS_SECRET_ACCESS_KEY" in event.prompt:
        return shared.outputs.Block(
            reason="Remove secrets before submitting this prompt."
        )
    return shared.outputs.AddContext(text="Inspect project tests before editing.")


@app.on(shared.events.ToolCallProposed)
def inspect_tool(
    event: shared.events.ToolCallProposed,
) -> shared.outputs.Result:
    if event.tool_name != "Bash" or not isinstance(event.tool_input, dict):
        return None
    command = event.tool_input.get("command")
    if isinstance(command, str) and "rm -rf /" in command:
        return shared.outputs.DenyTool(
            reason="Refusing destructive root command."
        )
    return None


@app.on(shared.events.PermissionRequested)
def inspect_permission(
    event: shared.events.PermissionRequested,
) -> shared.outputs.Result:
    if event.tool_name == "Bash":
        return shared.outputs.DenyPermission(
            reason="Bash permission requires manual approval."
        )
    return shared.outputs.AllowPermission()
```

Portable result intents are separate types rather than one object containing conditionally valid optional fields:

```text
SystemMessage
AddContext
Block
AllowTool / DenyTool
AllowPermission / DenyPermission
Stop
```

The translator validates each intent against the semantic event and target provider before rendering output.

## Describe the installed hookset

`hookset.toml` is the source of truth for registration and installation:

```toml
name = "repository-policy"
mode = "shared"
app = "hooks.py:app"
providers = ["codex", "claude_code"]

[[hooks]]
event = "PromptSubmitted"
timeout = 30
status_message = "Checking prompt policy"

[[hooks]]
event = "ToolCallProposed"
timeout = 30
status_message = "Checking tool policy"

[hooks.codex]
matcher = "Bash"

[hooks.claude_code]
matcher = "Bash"
if = "Bash(*)"
```

Shared defaults and provider-only overrides are distinct. Invalid combinations, such as Claude options when Claude Code is disabled, are rejected while parsing the hookset.

Provider-specific hooksets use provider-native event names and fields:

```toml
name = "codex-policy"
mode = "codex"
app = "hooks.py:app"

[[hooks]]
event = "PreToolUse"
matcher = "Bash"
timeout = 20
status_message = "Checking Bash command"
```

## Development lifecycle

Validate the hookset, import the application, and verify every configured event has a registered handler:

```bash
typed-agent-hooks check .agent-hooks/hookset.toml
```

Render provider-native configuration without writing files:

```bash
typed-agent-hooks render .agent-hooks/hookset.toml --provider all --pretty
```

Install into project-local provider files:

```bash
typed-agent-hooks install .agent-hooks/hookset.toml \
  --provider all \
  --scope project
```

This updates:

```text
.codex/hooks.json
.claude/settings.json
```

User-wide installation is explicit:

```bash
typed-agent-hooks install .agent-hooks/hookset.toml \
  --provider all \
  --scope user
```

Repeated installation replaces only the entries managed by the named hookset. It does not append duplicates. Existing unrelated provider settings and hooks are preserved.

Remove only this hookset's managed entries:

```bash
typed-agent-hooks uninstall .agent-hooks/hookset.toml \
  --provider all \
  --scope project
```

## Run and validate captured payloads

Provider-specific application:

```bash
typed-agent-hooks run codex hooks.py:app < payload.json
typed-agent-hooks run claude-code hooks.py:app < payload.json
```

Shared application requires an explicit concrete provider:

```bash
typed-agent-hooks run shared hooks.py:app --provider codex < payload.json
typed-agent-hooks run shared hooks.py:app --provider claude-code < payload.json
```

Validate without executing user hook code:

```bash
typed-agent-hooks validate codex < payload.json
typed-agent-hooks validate claude-code < payload.json
typed-agent-hooks validate claude-code --shared < payload.json
```

Print input JSON Schema:

```bash
typed-agent-hooks schema codex --pretty
typed-agent-hooks schema claude-code --pretty
typed-agent-hooks schema shared --pretty
```

## Strictness boundary

Outer event and output envelopes are closed Pydantic models:

```python
ConfigDict(
    extra="forbid",
    strict=True,
    populate_by_name=True,
    frozen=True,
)
```

`tool_input`, `tool_response`, and other provider-defined arbitrary JSON values remain `JsonValue`. They cannot honestly share one closed global schema because their shapes depend on the concrete built-in or MCP tool.

## Development

```bash
uv sync --all-groups
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest -q
```

The tests are intentionally weighted toward public-interface integration behavior: all provider event fixtures parse, wrong event/output combinations fail, shared mappings are explicit, and the complete init/check/render/install/reinstall/run/uninstall lifecycle is exercised.
