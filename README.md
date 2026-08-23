# typed-agent-hooks

`typed-agent-hooks` defines executable, code-first hooks for OpenAI Codex and Anthropic Claude Code. A hook's Python file owns its handlers, provider configuration, dependency environment, and executable entry point. There is no TOML manifest, import-string loader, or global installation CLI.

The package provides strict provider wire models, a conservative shared semantic API, preservation-oriented config reconciliation, ordered collections of independent hook executables, and an optional FastMCP bridge.

## One executable hook

Put the dependencies in the executable with PEP 723 and define configuration beside the handler:

```python
#!/usr/bin/env -S uv run --isolated --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "typed-agent-hooks @ git+https://github.com/nimashoghi/typed-agent-hooks.git@<commit>",
# ]
# ///
"""Add local project context to every submitted prompt."""

from cyclopts import App
from typed_agent_hooks import shared

cli = App(result_action="print_non_none_return_zero")
hooks = shared.HookApp(name="project-context")


@hooks.on(shared.events.PromptSubmitted, timeout=10)
def add_project_context(event: shared.events.PromptSubmitted) -> shared.outputs.Result:
    """Return context derived from one submitted prompt."""

    return shared.outputs.AddContext(text=f"Working directory: {event.context.cwd}")


@cli.command
def preview(prompt: str) -> str:
    """Preview the domain behavior without constructing a provider payload."""

    return f"Would add context for {prompt!r}"


if __name__ == "__main__":
    hooks.main(cli)
```

Make the file executable and run its ordinary domain CLI directly:

```console
./project_context.py preview "fix the tests"
```

`hooks.main(cli)` leaves ordinary arguments untouched for Cyclopts. Generated provider commands use a private `_typed-agent-hooks` protocol to invoke the same `hooks` object. That protocol is an implementation boundary, not a user-facing CLI.

The Python API is direct:

```python
tool = ipi.import_path("/path/to/project_context.py")
tool.preview("fix the tests")
tool.hooks.render("codex", executable=tool.__file__)
```

Keep docstrings on public functions. Cyclopts uses them for CLI help, and notebook callers get the same documentation from Python.

## Registration metadata

`HookApp.on` accepts shared defaults plus explicit provider-only overrides:

```python
@hooks.on(
    shared.events.ToolCallProposed,
    timeout=20,
    status_message="Checking tool call",
    codex=shared.CodexOptions(matcher="Bash"),
    claude_code=shared.ClaudeCodeOptions(matcher="Bash|Read"),
)
def check_tool(event: shared.events.ToolCallProposed) -> shared.outputs.Result:
    ...
```

An app declares its enabled providers when necessary:

```python
hooks = shared.HookApp(name="codex-only", providers=("codex",))
```

Shared events that do not exist on an enabled provider fail during rendering. Provider-specific options on a disabled provider also fail. The library does not guess a lossy translation.

For direct programmatic installation, call `HookApp.install` or `HookApp.uninstall`. Pass the executable explicitly so the Python call has the same information as the provider config:

```python
hooks.install(executable=__file__, provider="all", scope="project")
```

Installation replaces only commands marked with the app's stable name, preserves unrelated JSON fields and hooks, writes atomically, and reconciles every selected provider. Disabling a provider therefore removes that app's stale entries from the provider config.

## Ordered collections

Use a small executable installer when several hooks have independent dependencies or ownership:

```python
#!/usr/bin/env -S uv run --isolated --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "typed-agent-hooks @ git+https://github.com/nimashoghi/typed-agent-hooks.git@<commit>",
# ]
# ///
"""Install this repository's hooks in deterministic order."""

from pathlib import Path

from typed_agent_hooks import Collection

root = Path(__file__).parent
hooks = Collection(
    name="project-hooks",
    apps=(root / "first.py", root / "second.py"),
)

if __name__ == "__main__":
    hooks.main()
```

The CLI and Python API are the same bound methods:

```console
./install.py install --scope project
./install.py uninstall --scope project
```

```python
installer = ipi.import_path("/path/to/install.py")
installer.hooks.install(scope="project")
```

Collection installation executes each child in its own PEP 723 environment, validates every description before writing anything, preserves declared order, rejects duplicate names and paths, and removes members deleted from the collection.

## FastMCP forwarding

`typed_agent_hooks.fastmcp.attach` connects a running FastMCP server to a normal hook application. `ForwardingHooks` installs one forwarding command for every native event supported by each provider:

```python
from typed_agent_hooks.fastmcp import ForwardingHooks, attach

attach(server, hooks, provider="codex", server_name="ipi")

forwarding = ForwardingHooks(
    name="ipi",
    server_name="ipi",
    timeout=70,
    startup_wait=30,
    response_timeout=35,
)
forwarding.install(provider="all", scope="user")
```

The dedicated `tah-fastmcp-forward` entry point is also a direct Cyclopts view of the importable `forward` function:

```console
tah-fastmcp-forward - --provider codex --server-name ipi
```

```python
from typed_agent_hooks.fastmcp import forward

output = forward(payload, provider="codex", server_name="ipi")
```

`-` means stdin only at the CLI boundary. The forwarder is fail-open: an absent, slow, dead, unsupported, or ambiguous local bridge returns no output and does not block the harness. Invalid explicit timeout arguments still fail before forwarding.

The bridge requires the `fastmcp` extra. The forwarding subprocess itself imports Cyclopts and the small TAH rendezvous modules, but does not import FastMCP.

## Provider schemas

Provider-native schemas remain available from `typed_agent_hooks.codex` and `typed_agent_hooks.claude_code`. Wire inputs are tolerant readers: unknown provider fields are ignored while declared fields remain strictly typed. Outputs are closed and exact. Use the shared API when one semantic handler is valid for both providers; use the provider-native models when their behavior genuinely differs.

## Development

```console
uv run ruff check .
uv run ty check
uv run pytest -q
```
