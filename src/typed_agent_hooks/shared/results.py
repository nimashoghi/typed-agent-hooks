"""Portable result intents returned by shared-mode handlers."""

from typing import Literal, TypeAlias

from typed_agent_hooks.core import Json, StrictModel

from .events import AnyEvent, SharedEventName


class SharedOutputError(ValueError):
    """Raised when an output intent is not portable for an event/provider pair."""


class SystemMessage(StrictModel):
    """Show a provider system message without changing control flow."""

    kind: Literal["system_message"] = "system_message"
    message: str


class AddContext(StrictModel):
    """Add semantic context to the current event."""

    kind: Literal["context"] = "context"
    text: str
    system_message: str | None = None


class Block(StrictModel):
    """Block a blockable shared event."""

    kind: Literal["block"] = "block"
    reason: str
    context: str | None = None
    system_message: str | None = None


class AllowTool(StrictModel):
    """Allow a proposed tool call, optionally rewriting its input."""

    kind: Literal["allow_tool"] = "allow_tool"
    reason: str | None = None
    updated_input: Json | None = None
    context: str | None = None
    system_message: str | None = None


class DenyTool(StrictModel):
    """Deny a proposed tool call with an explicit reason."""

    kind: Literal["deny_tool"] = "deny_tool"
    reason: str
    context: str | None = None
    system_message: str | None = None


class AllowPermission(StrictModel):
    """Approve a provider permission request without provider-only mutations."""

    kind: Literal["allow_permission"] = "allow_permission"
    system_message: str | None = None


class DenyPermission(StrictModel):
    """Reject a provider permission request with an explicit reason."""

    kind: Literal["deny_permission"] = "deny_permission"
    reason: str
    system_message: str | None = None


class Stop(StrictModel):
    """Ask the provider to stop processing with a reason."""

    kind: Literal["stop"] = "stop"
    reason: str
    system_message: str | None = None


Result: TypeAlias = (
    SystemMessage
    | AddContext
    | Block
    | AllowTool
    | DenyTool
    | AllowPermission
    | DenyPermission
    | Stop
    | None
)

CONTEXT_EVENTS: frozenset[SharedEventName] = frozenset(
    {
        "SessionStarted",
        "PromptSubmitted",
        "ToolCallProposed",
        "ToolCallCompleted",
        "SubagentStarted",
    }
)
BLOCK_EVENTS: frozenset[SharedEventName] = frozenset(
    {
        "PromptSubmitted",
        "ToolCallCompleted",
        "CompactionStarting",
        "SubagentStopped",
        "TurnStopped",
    }
)
STOP_EVENTS: frozenset[SharedEventName] = frozenset(
    {
        "SessionStarted",
        "PromptSubmitted",
        "ToolCallCompleted",
        "CompactionStarting",
        "CompactionFinished",
        "SubagentStopped",
        "TurnStopped",
    }
)


def require_event(event: AnyEvent, allowed: frozenset[SharedEventName], output: object) -> None:
    """Require that an output intent is portable for a shared event."""

    if event.event_name not in allowed:
        raise SharedOutputError(f"{type(output).__name__} is not portable for {event.event_name}")
