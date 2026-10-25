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
    """Block a blockable shared event.

    It carries no context: Codex keeps a blocked prompt's context for the next
    turn, Claude Code drops it, and Codex cannot carry it on a stop block.
    """

    reason: str
    system_message: str | None = None


class AllowTool(StrictModel):
    """Allow a proposed tool call, optionally rewriting its input.

    The hosts differ. Claude Code skips its permission prompt and uses
    ``updated_input`` when it is set. Codex only applies ``updated_input``,
    and its normal approval still runs; Codex rejects an allow without
    ``updated_input``, so that result raises ``SharedOutputError`` for Codex.
    """

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

# The compaction events are in no set: Claude Code ignores systemMessage and
# continue on them, and a block means different things in the two hosts.
MESSAGE_EVENTS: frozenset[SharedEventName] = frozenset(
    {
        "SessionStarted",
        "PromptSubmitted",
        "ToolCallProposed",
        "PermissionRequested",
        "ToolCallCompleted",
        "ToolCallFailed",
        "SubagentStarted",
        "SubagentStopped",
        "TurnStopped",
    }
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
# Not ToolCallCompleted: Claude Code keeps the tool output next to the
# reason, while Codex replaces the output with the reason.
BLOCK_EVENTS: frozenset[SharedEventName] = frozenset(
    {"PromptSubmitted", "SubagentStopped", "TurnStopped"}
)
# Not SessionStarted (Claude Code has no decision control there) and not
# ToolCallCompleted (Codex turns the stop into model feedback and continues).
STOP_EVENTS: frozenset[SharedEventName] = frozenset(
    {"PromptSubmitted", "SubagentStopped", "TurnStopped"}
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
        if event.event_name in ("CompactionStarting", "CompactionFinished"):
            message += (
                ". Compaction events only observe; for context after compaction, return "
                "AddContext from SessionStarted(source='compact')"
            )
        raise SharedOutputError(message)
