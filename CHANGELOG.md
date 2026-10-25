# Changelog

## 0.3.0

This release is breaking. The package keeps only the shared typed event layer and the Codex and Claude Code wire schemas. The host files now hold all host configuration.

Changed:

- `HookApp(name=...)` takes only a name. `@app.on(EventType)` takes only the event type.
- `app.main()` takes the host from its first argument (`codex` or `claude`) and the event from the payload's `hook_event_name`. A failure, including a handler `sys.exit`, writes one line on stderr and exits 0. Everything else that the process writes to stdout, including a print at import and child processes, goes to stderr. A missing or unknown host argument writes a usage line and exits 1.
- `app.handle(host, payload)` replaces `handle_json`, `handle_codex_event` and `handle_claude_code_event`.
- `app.handlers` maps shared event types, not event names, to handlers.
- `EventContext.host` (`"codex"` or `"claude"`) replaces `EventContext.provider`.
- `shared.events.EVENT_TYPES` replaces `EVENT_NAMES` and `EVENT_NAME_BY_TYPE`. `shared.events.AnyEvent` is a plain union.
- `codex.events.INPUT_TYPES` and `claude_code.events.INPUT_TYPES` (input model by native event name) replace `EVENT_NAMES` and `INPUT_ADAPTER` in each host package. `parse_input` validates only the model that `hook_event_name` names, and raises `ValueError` for an unsupported name. `AnyInput` is a plain union.
- All models set `defer_build`, so a hook run builds only the schemas that it uses. This saves about 12 ms per hook run.

Added:

- `shared.native_event_name(event_type, host)`: the native event name of a shared event type in each host.

Fixed:

- `CompactionStarting` and `CompactionFinished` accept no result. Before, `SystemMessage` and `Stop` on them did nothing in Claude Code, and `Block` on `CompactionStarting` skipped the compaction in Claude Code but stopped the turn in Codex.
- `AllowTool` without `updated_input` raises `SharedOutputError` in Codex. Before, Codex rejected the output and dropped its context. With `updated_input`, Claude Code skips its permission prompt and Codex still runs its normal approval; the docstring and README say so.
- `Block` on `ToolCallCompleted` raises in both hosts. Claude Code kept the tool output next to the reason, while Codex replaced the output with the reason.
- `Stop` on `SessionStarted` or `ToolCallCompleted` raises in both hosts. Claude Code has no decision control on `SessionStart`, and Codex turned a stop on `PostToolUse` into model feedback and continued the turn.
- `Block` has no `context` field. Before, a stop block with context rendered for Claude Code and raised for Codex, and a blocked prompt's context reached the next turn in Codex but not in Claude Code.
- A Claude Code `PreCompact` payload with `custom_instructions: null` (automatic compaction, or `/compact` with no text) parses. It failed validation before, so the hook did not run.
- `SystemMessage` on a Claude Code `ToolCallFailed` event renders a `PostToolUseFailure` output. It raised `AssertionError` before.
- `AddContext` is valid on `ToolCallFailed`. Claude Code sends a failed tool call as `PostToolUseFailure`, which accepts additional context, so a hook can add context after every finished tool call in both hosts.

Removed:

- Host configuration generation and installation: `Collection`, `HookApp.render`, `describe`, `install`, `uninstall`, `registrations`, the `reconcile_*` functions, `shared.CodexOptions`, `shared.ClaudeCodeOptions`, the `codex.config` and `claude_code.config` modules, and the default Windows `commandWindows` command.
- The private `_typed-agent-hooks run --managed-app` protocol and the `HookApp.main(cli)` fallback to a domain CLI.
- The `HookApp(providers=...)` option.
- The FastMCP forwarder and bridge (`typed_agent_hooks.fastmcp`), the `fastmcp` extra, the `tah-fastmcp-forward` console script, and `EventContext.response_available`.
- The Claude Code schemas of the 19 events that have no shared equivalent (`Setup`, `InstructionsLoaded`, `UserPromptExpansion`, `MessageDisplay`, `PostToolBatch`, `PermissionDenied`, `Notification`, `TaskCreated`, `TaskCompleted`, `StopFailure`, `TeammateIdle`, `ConfigChange`, `CwdChanged`, `FileChanged`, `WorktreeCreate`, `WorktreeRemove`, `SessionEnd`, `Elicitation`, `ElicitationResult`) and their outputs, `core.PlainTextOutput`, and `claude_code.outputs.WorktreePathOutput`. No shared path reached them.
- Wire fields that no shared event reads or no shared result writes. Inputs: Claude Code `effort`, `permission_suggestions`, `background_tasks` and `session_crons`, so a host change to them cannot break a hook. Outputs: `suppressOutput`, Claude Code `terminalSequence`, `initialUserMessage`, `sessionTitle`, `watchPaths`, `reloadSkills`, `suppressOriginalPrompt`, the `ask` and `defer` permission decisions, `updatedPermissions`, the permission-request `updatedInput` and `interrupt`, `updatedToolOutput` and `updatedMCPToolOutput`, and the Codex `PreToolUse` `decision` and `reason`. `core.ClaudeCommonOutput` is merged into `core.CommonOutput`, which now holds only `systemMessage`; `continue`, `stopReason`, `decision` and `reason` are on `core.BlockableOutput`, the base of the outputs of `UserPromptSubmit`, `Stop` and `SubagentStop` in both hosts.
- `shared.try_from_claude_code`, `shared.NoSharedMappingError`, `shared.parse_codex` and `shared.parse_claude_code`. `app.handle` replaces the parse helpers.
- The `shared` exports `adapters`, `from_codex` and `from_claude_code`, and `shared.outputs.to_codex_output` and `to_claude_code_output`. The converters are in the private modules `shared.adapters`, `shared.codex_outputs` and `shared.claude_code_outputs`. `shared.results` is merged into `shared.outputs`.
- The `kind` field of each shared result.
- `codex.outputs.LifecycleOutput`, `claude_code.outputs.PreCompactOutput`, `claude_code.outputs.PostCompactOutput`, `claude_code.outputs.SubagentStopSpecificOutput` and `claude_code.outputs.StopSpecificOutput`. No shared result writes them.
- The validation aliases of the output models and `populate_by_name`. Nothing parses host JSON into an output model, so output models take only Python field names. They still write the host names.
- The output validators that the shared converters cannot trigger: `updatedInput` without an allow decision, and a message on an allowed permission request. The block-reason validators stay.
- `codex.render_output` and `claude_code.render_output`, with their check of the output type. The shared converters always produce the right type, and `HookApp.handle` renders with `core.render_json`.
- `typed_agent_hooks.registry`, `core.Provider`, `shared.outputs.to_provider_output`, `shared.events.EVENT_ADAPTER`, `EVENT_NAME_BY_TYPE` in the host packages, and the stale `__version__`.
- The `cyclopts` and `pydantic-core` dependencies.
