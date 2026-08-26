"""Public shared output intents and provider conversion functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from typed_agent_hooks.core import Provider, StrictModel

from .events import AnyEvent
from .results import (
    AddContext,
    AllowPermission,
    AllowTool,
    Block,
    DenyPermission,
    DenyTool,
    Result,
    SharedOutputError,
    Stop,
    SystemMessage,
)

if TYPE_CHECKING:
    from typed_agent_hooks import claude_code, codex


def to_codex_output(event: AnyEvent, output: Result) -> codex.outputs.HookResult:
    """Convert a shared result after lazily loading Codex wire schemas."""

    from .codex_outputs import to_codex_output as convert

    return convert(event, output)


def to_claude_code_output(
    event: AnyEvent,
    output: Result,
) -> claude_code.outputs.HookResult:
    """Convert a shared result after lazily loading Claude Code wire schemas."""

    from .claude_code_outputs import to_claude_code_output as convert

    return convert(event, output)


def _require_structured(output: object) -> StrictModel | None:
    if output is None:
        return None
    if not isinstance(output, StrictModel):
        raise TypeError("shared mode only supports structured provider outputs")
    return output


def to_provider_output(event: AnyEvent, output: Result) -> StrictModel | None:
    """Convert a shared result according to the event's explicit provider."""

    if event.context.provider is Provider.CODEX:
        return _require_structured(to_codex_output(event, output))
    return _require_structured(to_claude_code_output(event, output))


__all__ = [
    "AddContext",
    "AllowPermission",
    "AllowTool",
    "Block",
    "DenyPermission",
    "DenyTool",
    "Result",
    "SharedOutputError",
    "Stop",
    "SystemMessage",
    "to_claude_code_output",
    "to_codex_output",
    "to_provider_output",
]
