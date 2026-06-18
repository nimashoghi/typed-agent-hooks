"""Pure runtime operations used by the command-line interface."""

from pathlib import Path
from typing import Literal, TypeAlias

from pydantic import BaseModel, TypeAdapter

from typed_agent_hooks import claude_code, codex, shared
from typed_agent_hooks.core import JsonInput, Provider
from typed_agent_hooks.loader import load_object

Mode: TypeAlias = Literal["codex", "claude_code", "shared"]


def run_hook(
    mode: Mode,
    app_spec: str,
    payload: JsonInput,
    *,
    provider: Provider | None = None,
    base_dir: str | Path | None = None,
) -> str | None:
    """Load one app and run one command-hook payload."""

    app = load_object(app_spec, base_dir=base_dir)
    if mode == "codex":
        if provider is not None and provider is not Provider.CODEX:
            raise ValueError("Codex mode cannot run a Claude Code payload")
        if not isinstance(app, codex.HookApp):
            raise TypeError("Codex mode requires a codex.HookApp")
        return app.handle_json(payload)

    if mode == "claude_code":
        if provider is not None and provider is not Provider.CLAUDE_CODE:
            raise ValueError("Claude Code mode cannot run a Codex payload")
        if not isinstance(app, claude_code.HookApp):
            raise TypeError("Claude Code mode requires a claude_code.HookApp")
        return app.handle_json(payload)

    if provider is None:
        raise ValueError("shared mode requires an explicit provider")
    if not isinstance(app, shared.HookApp):
        raise TypeError("shared mode requires a shared.HookApp")
    return app.handle_json(provider, payload)


def validate_input(
    provider: Provider,
    payload: JsonInput,
    *,
    shared_mode: bool = False,
) -> BaseModel:
    """Validate provider input, optionally requiring a shared mapping."""

    if provider is Provider.CODEX:
        codex_event = codex.parse_input(payload)
        return shared.from_codex(codex_event) if shared_mode else codex_event

    claude_event = claude_code.parse_input(payload)
    return shared.from_claude_code(claude_event) if shared_mode else claude_event


def input_schema(mode: Mode) -> dict[str, object]:
    """Return JSON Schema for a provider or shared input union."""

    if mode == "codex":
        return codex.INPUT_ADAPTER.json_schema()
    if mode == "claude_code":
        return claude_code.INPUT_ADAPTER.json_schema()
    return TypeAdapter(shared.events.AnyEvent).json_schema()
