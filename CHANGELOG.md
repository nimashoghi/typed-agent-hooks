# Changelog

## 0.3.0

This release is breaking. The package keeps only the shared typed event layer and the Codex and Claude Code wire schemas. The host files now hold all host configuration.

Changed:

- `HookApp(name=...)` takes only a name. `@app.on(EventType)` takes only the event type.
- `app.main()` takes the host from its first argument (`codex` or `claude`) and the event from the payload's `hook_event_name`. A failure writes one line on stderr and exits 0. A missing or unknown host argument writes a usage line and exits 1.
- `app.handle(host, payload)` replaces `handle_json`, `handle_codex_event` and `handle_claude_code_event`.
- `app.handlers` maps shared event types, not event names, to handlers.
- `EventContext.host` (`"codex"` or `"claude"`) replaces `EventContext.provider`.
- `shared.events.EVENT_TYPES` replaces `EVENT_NAMES` and `EVENT_NAME_BY_TYPE`. `shared.events.AnyEvent` is a plain union.

Added:

- `shared.native_event_name(event_type, host)`: the native event name of a shared event type in each host.

Removed:

- Host configuration generation and installation: `Collection`, `HookApp.render`, `describe`, `install`, `uninstall`, `registrations`, the `reconcile_*` functions, `shared.CodexOptions`, `shared.ClaudeCodeOptions`, the `codex.config` and `claude_code.config` modules, and the default Windows `commandWindows` command.
- The private `_typed-agent-hooks run --managed-app` protocol and the `HookApp.main(cli)` fallback to a domain CLI.
- The `HookApp(providers=...)` option.
- The FastMCP forwarder and bridge (`typed_agent_hooks.fastmcp`), the `fastmcp` extra, the `tah-fastmcp-forward` console script, and `EventContext.response_available`.
- `typed_agent_hooks.registry`, `core.Provider`, `shared.outputs.to_provider_output`, `shared.events.EVENT_ADAPTER`, the `EVENT_NAME_BY_TYPE` and `INPUT_ADAPTER` exports of the host packages, and the stale `__version__`.
- The `cyclopts` and `pydantic-core` dependencies.
