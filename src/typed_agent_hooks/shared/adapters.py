"""Explicit provider-to-shared event adapters."""

from __future__ import annotations

from typed_agent_hooks import claude_code, codex
from typed_agent_hooks.core import JsonInput, Provider

from .events import (
    AnyEvent,
    CompactionFinished,
    CompactionStarting,
    EventContext,
    PermissionRequested,
    PromptSubmitted,
    SessionStarted,
    SubagentStarted,
    SubagentStopped,
    ToolCallCompleted,
    ToolCallProposed,
    TurnStopped,
)


class NoSharedMappingError(ValueError):
    """Raised when a provider-only event has no shared semantic mapping."""


def _codex_context(event: codex.events.AnyInput) -> EventContext:
    if isinstance(
        event,
        (
            codex.events.SessionStartInput,
            codex.events.SubagentStartInput,
            codex.events.PreToolUseInput,
            codex.events.PermissionRequestInput,
            codex.events.PostToolUseInput,
            codex.events.UserPromptSubmitInput,
            codex.events.SubagentStopInput,
            codex.events.StopInput,
        ),
    ):
        permission_mode = event.permission_mode
    else:
        permission_mode = None
    return EventContext(
        provider=Provider.CODEX,
        source_event=event.hook_event_name,
        session_id=event.session_id,
        transcript_path=event.transcript_path,
        cwd=event.cwd,
        model=event.model,
        permission_mode=permission_mode,
    )


def _claude_context(event: claude_code.events.AnyInput) -> EventContext:
    model = event.model if isinstance(event, claude_code.events.SessionStartInput) else None
    return EventContext(
        provider=Provider.CLAUDE_CODE,
        source_event=event.hook_event_name,
        session_id=event.session_id,
        transcript_path=event.transcript_path,
        cwd=event.cwd,
        model=model,
        permission_mode=event.permission_mode,
    )


def from_codex(event: codex.events.AnyInput) -> AnyEvent:
    """Map a Codex wire event into its shared semantic event."""

    context = _codex_context(event)
    match event:
        case codex.events.SessionStartInput():
            return SessionStarted(context=context, source=event.source)
        case codex.events.UserPromptSubmitInput():
            return PromptSubmitted(context=context, turn_id=event.turn_id, prompt=event.prompt)
        case codex.events.PreToolUseInput():
            return ToolCallProposed(
                context=context,
                turn_id=event.turn_id,
                tool_name=event.tool_name,
                tool_input=event.tool_input,
                tool_use_id=event.tool_use_id,
            )
        case codex.events.PermissionRequestInput():
            return PermissionRequested(
                context=context,
                turn_id=event.turn_id,
                tool_name=event.tool_name,
                tool_input=event.tool_input,
            )
        case codex.events.PostToolUseInput():
            return ToolCallCompleted(
                context=context,
                turn_id=event.turn_id,
                tool_name=event.tool_name,
                tool_input=event.tool_input,
                tool_response=event.tool_response,
                tool_use_id=event.tool_use_id,
            )
        case codex.events.PreCompactInput():
            return CompactionStarting(context=context, turn_id=event.turn_id, trigger=event.trigger)
        case codex.events.PostCompactInput():
            return CompactionFinished(context=context, turn_id=event.turn_id, trigger=event.trigger)
        case codex.events.SubagentStartInput():
            return SubagentStarted(
                context=context,
                turn_id=event.turn_id,
                agent_id=event.agent_id,
                agent_type=event.agent_type,
            )
        case codex.events.SubagentStopInput():
            return SubagentStopped(
                context=context,
                turn_id=event.turn_id,
                agent_id=event.agent_id,
                agent_type=event.agent_type,
                agent_transcript_path=event.agent_transcript_path,
                stop_hook_active=event.stop_hook_active,
                last_assistant_message=event.last_assistant_message,
            )
        case codex.events.StopInput():
            return TurnStopped(
                context=context,
                turn_id=event.turn_id,
                stop_hook_active=event.stop_hook_active,
                last_assistant_message=event.last_assistant_message,
            )
    raise AssertionError(f"unmapped Codex event type: {type(event).__name__}")


def try_from_claude_code(event: claude_code.events.AnyInput) -> AnyEvent | None:
    """Return a shared event, or ``None`` for a Claude Code-only event."""

    context = _claude_context(event)
    match event:
        case claude_code.events.SessionStartInput():
            return SessionStarted(
                context=context, source=event.source, session_title=event.session_title
            )
        case claude_code.events.UserPromptSubmitInput():
            return PromptSubmitted(context=context, prompt=event.prompt)
        case claude_code.events.PreToolUseInput():
            return ToolCallProposed(
                context=context,
                tool_name=event.tool_name,
                tool_input=event.tool_input,
                tool_use_id=event.tool_use_id,
            )
        case claude_code.events.PermissionRequestInput():
            return PermissionRequested(
                context=context,
                tool_name=event.tool_name,
                tool_input=event.tool_input,
            )
        case claude_code.events.PostToolUseInput():
            return ToolCallCompleted(
                context=context,
                tool_name=event.tool_name,
                tool_input=event.tool_input,
                tool_response=event.tool_response,
                tool_use_id=event.tool_use_id,
                duration_ms=event.duration_ms,
            )
        case claude_code.events.PreCompactInput():
            return CompactionStarting(
                context=context,
                trigger=event.trigger,
                instructions=event.custom_instructions,
            )
        case claude_code.events.PostCompactInput():
            return CompactionFinished(
                context=context,
                trigger=event.trigger,
                summary=event.compact_summary,
            )
        case claude_code.events.SubagentStartInput():
            return SubagentStarted(
                context=context,
                agent_id=event.agent_id,
                agent_type=event.agent_type,
            )
        case claude_code.events.SubagentStopInput():
            return SubagentStopped(
                context=context,
                agent_id=event.agent_id,
                agent_type=event.agent_type,
                agent_transcript_path=event.agent_transcript_path,
                stop_hook_active=event.stop_hook_active,
                last_assistant_message=event.last_assistant_message,
            )
        case claude_code.events.StopInput():
            return TurnStopped(
                context=context,
                stop_hook_active=event.stop_hook_active,
                last_assistant_message=event.last_assistant_message,
            )
    return None


def from_claude_code(event: claude_code.events.AnyInput) -> AnyEvent:
    """Map a Claude Code wire event, failing if no shared mapping exists."""

    mapped = try_from_claude_code(event)
    if mapped is None:
        raise NoSharedMappingError(
            f"Claude Code event {event.hook_event_name} has no shared semantic mapping"
        )
    return mapped


def parse_codex(data: JsonInput) -> AnyEvent:
    """Parse Codex input and map it into shared mode."""

    return from_codex(codex.parse_input(data))


def parse_claude_code(data: JsonInput) -> AnyEvent:
    """Parse Claude Code input and require a shared mapping."""

    return from_claude_code(claude_code.parse_input(data))
