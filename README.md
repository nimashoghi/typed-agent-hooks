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

## FastMCP bridge (`[fastmcp]` extra)

A long-lived FastMCP **stdio** server can receive harness hook events in-process via the optional
`fastmcp` extra. A thin `forward` shim (run by the harness as a `command` hook) relays each event over
a unix socket to the running server, which dispatches it through a normal `HookApp` whose handlers
close over live server state (e.g. an IPython kernel pool).

```bash
pip install "typed-agent-hooks[fastmcp]"
```

Server side (only this imports `fastmcp`): attach a bridge after creating the server and before running it.

```python
from fastmcp import FastMCP
from typed_agent_hooks import codex
from typed_agent_hooks.core import PlainTextOutput
from typed_agent_hooks.fastmcp import attach

mcp = FastMCP("ipi")
app = codex.HookApp()


@app.on(codex.events.SessionStartInput)
def reground(event: codex.events.SessionStartInput) -> codex.outputs.HookResult:
    if event.source != "compact":
        return None
    return PlainTextOutput(text=server_state_summary())  # closes over live server state


attach(mcp, app, provider="codex", server_name="ipi")
mcp.run()  # stdio
```

`attach(server, hook_app, *, provider, server_name="ipi", registry_root=None)` accepts a `codex`,
`claude_code`, or `shared` `HookApp`. Handlers use the usual `@app.on(...)` decorator; the only new
idea is that they may reach server state through the same lock-guarding API the tools use.

Install the hooks with a `mode = "fastmcp"` hookset (no `app` — the dispatch app lives in the server).
Scope the tool-event matchers to the server's own tools so binding happens on a real call:

```toml
name = "ipi-hooks"
mode = "fastmcp"
provider = "codex"
server = "ipi"

[[hooks]]
event = "SessionStart"

[[hooks]]
event = "PreToolUse"
matcher = "^(create_kernel|cell|switch_kernel|list_active_kernels|pdb)$"
```

```bash
typed-agent-hooks install ipi-hooks.toml --provider codex --scope project
```

This writes the `forward` command
(`python -m typed_agent_hooks forward --provider codex --server-name ipi --hookset-name ipi-hooks`)
into `.codex/hooks.json`, idempotently and uninstallably (keyed on the `--hookset-name` marker). For
Claude Code use `provider = "claude_code"` with a `mcp__<server>__.*` matcher.

### Rendezvous

The shim must reach the *correct* server, including when one harness process hosts a main agent and
subagents that each spawn their own server (Codex). Both the shim and the server independently locate
the harness process (their lowest common ancestor) and a per-uid registry under `/run/user/<uid>`
(or `$TMPDIR`). A server self-identifies by:

- **Claude Code**: `CLAUDE_CODE_SESSION_ID` from its environment (eager bind);
- **Codex**: `_meta.threadId` read from the first tool call via an `on_call_tool` middleware (lazy bind).

The shim keys on `agent_id` (codex `Subagent{Start,Stop}`) else `session_id`, forwards to the matching
server, and **fails open** (exits 0, no output) whenever no unambiguous server is found. The shim plus
the `rendezvous`/`wire` modules import no `fastmcp`, so they run in the bare harness hook subprocess.

### Limitations

- Linux only for v1 (`/proc` + `AF_UNIX` + `SO_PEERCRED`); elsewhere the shim fails open (no-op).
- A Codex subagent's *tool* hooks carry only the parent `session_id`, so when multiple subagent servers
  coexist they are deliberately a safe no-op rather than risk misrouting; `Subagent{Start,Stop}` (which
  carry `agent_id`) buffer-and-resolve. A subagent that never calls a tool never binds, so its start-hook
  output cannot be delivered.
- Requires `fastmcp >= 3.3, < 3.4` (the bridge depends on the single-`_lifespan` wrap and the
  `request_context.meta` passthrough).

The rendezvous was verified live on Codex (`_meta.threadId` reaches the middleware; root
`threadId == session_id`, subagent `threadId == agent_id`) and the Claude env-bind corroborated.

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
