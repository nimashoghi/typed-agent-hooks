"""Portable results that shared-event handlers return."""

from typing import TypeAlias

from typed_agent_hooks.core import Json, StrictModel

from .events import AnyEvent, SharedEventName


class SharedOutputError(ValueError):
    """Raised when an output intent is not portable for an event and host."""


class SystemMessage(StrictModel):
    """Show a host system message without changing control flow."""

    message: str


class AddContext(StrictModel):
    """Add semantic context to the current event."""

    text: str
    system_message: str | None = None


class Block(StrictModel):
    """Block a blockable shared event."""

    reason: str
    context: str | None = None
    system_message: str | None = None


class AllowTool(StrictModel):
    """Allow a proposed tool call, optionally rewriting its input."""

    reason: str | None = None
    updated_input: Json | None = None
    context: str | None = None
    system_message: str | None = None


class DenyTool(StrictModel):
    """Deny a proposed tool call with an explicit reason."""

    reason: str
    context: str | None = None
    system_message: str | None = None


class AllowPermission(StrictModel):
    """Approve a host permission request without host-only mutations."""

    system_message: str | None = None


class DenyPermission(StrictModel):
    """Reject a host permission request with an explicit reason."""

    reason: str
    system_message: str | None = None


class Stop(StrictModel):
    """Ask the host to stop processing with a reason."""

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
        "ToolCallFailed",
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
        valid_events = ", ".join(sorted(allowed))
        message = (
            f"{type(output).__name__} is not portable for {event.event_name} "
            f"({event.context.host} {event.context.source_event}); "
            f"valid events: {valid_events}"
        )
        if isinstance(output, AddContext) and event.event_name == "CompactionFinished":
            message += (
                ". Return post-compaction context from SessionStarted(source='compact') instead"
            )
        raise SharedOutputError(message)
