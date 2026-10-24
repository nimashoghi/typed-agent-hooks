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
- `codex.INPUT_TYPES` and `claude_code.INPUT_TYPES` (input model by native event name) replace `EVENT_NAMES` and `INPUT_ADAPTER` in each host package. `parse_input` validates only the model that `hook_event_name` names, and raises `ValueError` for an unknown name. `AnyInput` is a plain union.
- All models set `defer_build`, so a hook run builds only the schemas that it uses. A Claude Code hook run is about 20 ms faster.

Added:

- `shared.native_event_name(event_type, host)`: the native event name of a shared event type in each host.

Removed:

- Host configuration generation and installation: `Collection`, `HookApp.render`, `describe`, `install`, `uninstall`, `registrations`, the `reconcile_*` functions, `shared.CodexOptions`, `shared.ClaudeCodeOptions`, the `codex.config` and `claude_code.config` modules, and the default Windows `commandWindows` command.
- The private `_typed-agent-hooks run --managed-app` protocol and the `HookApp.main(cli)` fallback to a domain CLI.
- The `HookApp(providers=...)` option.
- The FastMCP forwarder and bridge (`typed_agent_hooks.fastmcp`), the `fastmcp` extra, the `tah-fastmcp-forward` console script, and `EventContext.response_available`.
- `typed_agent_hooks.registry`, `core.Provider`, `shared.outputs.to_provider_output`, `shared.events.EVENT_ADAPTER`, `EVENT_NAME_BY_TYPE` in the host packages, and the stale `__version__`.
- The `cyclopts` and `pydantic-core` dependencies.
