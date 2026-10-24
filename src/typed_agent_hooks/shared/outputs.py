"""Public shared output intents and host conversion functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

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
]
