"""Explicit host-to-shared event adapters."""

from itertools import islice
from pathlib import Path

from typed_agent_hooks import agy, claude_code, codex
from typed_agent_hooks.core import Host, loads_json

from .events import (
    AnyEvent,
    BaseEvent,
    CompactionFinished,
    CompactionStarting,
    EventContext,
    PermissionRequested,
    PromptSubmitted,
    SessionStarted,
    SubagentStarted,
    SubagentStopped,
    ToolCallCompleted,
    ToolCallFailed,
    ToolCallProposed,
    TurnStopped,
)

NATIVE_EVENT_NAMES: dict[Host, dict[type[BaseEvent], str]] = {
    "codex": {
        SessionStarted: "SessionStart",
        PromptSubmitted: "UserPromptSubmit",
        ToolCallProposed: "PreToolUse",
        PermissionRequested: "PermissionRequest",
        ToolCallCompleted: "PostToolUse",
        CompactionStarting: "PreCompact",
        CompactionFinished: "PostCompact",
        SubagentStarted: "SubagentStart",
        SubagentStopped: "SubagentStop",
        TurnStopped: "Stop",
    },
    "claude": {
        SessionStarted: "SessionStart",
        PromptSubmitted: "UserPromptSubmit",
        ToolCallProposed: "PreToolUse",
        PermissionRequested: "PermissionRequest",
        ToolCallCompleted: "PostToolUse",
        ToolCallFailed: "PostToolUseFailure",
        CompactionStarting: "PreCompact",
        CompactionFinished: "PostCompact",
        SubagentStarted: "SubagentStart",
        SubagentStopped: "SubagentStop",
        TurnStopped: "Stop",
    },
    # agy has no prompt event. PreInvocation fires before every model call;
    # the adapter reports PromptSubmitted only for a call that answers a
    # user prompt. PostToolUse carries both a completed and a failed call.
    "agy": {
        SessionStarted: "SessionStart",
        PromptSubmitted: "PreInvocation",
        ToolCallProposed: "PreToolUse",
        ToolCallCompleted: "PostToolUse",
        ToolCallFailed: "PostToolUse",
        TurnStopped: "Stop",
    },
}


def native_event_name(event_type: type[BaseEvent], host: Host) -> str | None:
    """Return the host's native hook event name for a shared event type.

    Returns ``None`` when the host has no such event (Codex has no
    ``ToolCallFailed``, and agy has no permission, compaction or subagent
    events). Host files register a hook under this name.
    """

    return NATIVE_EVENT_NAMES[host].get(event_type)


def _codex_context(event: codex.events.AnyInput) -> EventContext:
    return EventContext(
        host="codex",
        source_event=event.hook_event_name,
        session_id=event.session_id,
        transcript_path=event.transcript_path,
        cwd=event.cwd,
        model=event.model,
        permission_mode=event.permission_mode,
        agent_id=event.agent_id,
        agent_type=event.agent_type,
    )


def _claude_context(event: claude_code.events.AnyInput) -> EventContext:
    model = event.model if isinstance(event, claude_code.events.SessionStartInput) else None
    return EventContext(
        host="claude",
        source_event=event.hook_event_name,
        session_id=event.session_id,
        transcript_path=event.transcript_path,
        cwd=event.cwd,
        model=model,
        permission_mode=event.permission_mode,
        agent_id=event.agent_id,
        agent_type=event.agent_type,
        prompt_id=event.prompt_id,
        scratchpad_dir=event.scratchpad_dir,
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


def from_claude_code(event: claude_code.events.AnyInput) -> AnyEvent:
    """Map a Claude Code wire event into its shared semantic event."""

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
        case claude_code.events.PostToolUseFailureInput():
            return ToolCallFailed(
                context=context,
                tool_name=event.tool_name,
                tool_input=event.tool_input,
                tool_use_id=event.tool_use_id,
                error=event.error,
                is_interrupt=event.is_interrupt,
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
    raise AssertionError(f"unmapped Claude Code event type: {type(event).__name__}")


def _answers_user_input(transcript: Path, steps: int) -> bool:
    """Whether the first model call of a run answers a user prompt.

    A user prompt, a message from ``agentapi send-message`` and a Stop hook
    that continues the turn all start a run, and agy gives each the previous
    prompt as ``lastUserInput``. The transcript holds one JSON step per line.
    Before a call that answers a prompt, the last of the first ``steps`` steps
    that is not a system message (which hooks inject after the prompt) is the
    user's input. Before any other call, it is the model's response or a tool
    result.
    """

    if steps == 0:
        return False  # an empty prefix holds no prompt
    count, last = 0, None
    # Binary lines: a step after the prefix, even one that is not UTF-8, is not read.
    with transcript.open("rb") as lines:
        for line in islice(lines, steps):
            count += 1
            step = loads_json(line.decode("utf-8"))
            kind = step.get("type") if isinstance(step, dict) else None
            if not isinstance(kind, str):
                raise ValueError(f"{transcript} has a step without a type")
            if kind != "SYSTEM_MESSAGE":
                last = kind
    if count < steps:
        raise ValueError(f"{transcript} has {count} steps, fewer than initialNumSteps {steps}")
    return last == "USER_INPUT"


# agy's terminationReason values for a run that the model finished, and the
# documented ones for a run that it did not (agy's hooks documentation).
AGY_FINISHED = frozenset({"NO_TOOL_CALL", "TERMINAL_STEP_TYPE"})
AGY_UNFINISHED = frozenset(
    {
        "MAX_INVOCATIONS",
        "MAX_FORCED_INVOCATIONS",
        "MAX_TOKEN_BUDGET_EXCEEDED",
        "ERROR",
        "USER_CANCELED",
        "TERMINAL_CUSTOM_HOOK",
        "INJECTED_RESPONSE",
    }
)


def from_agy(event: agy.events.AnyInput) -> AnyEvent | None:
    """Map an agy wire event into its shared semantic event.

    Returns ``None`` for a PreInvocation that does not answer a user prompt
    (one after the first model call of a run, or the first call of a run that a
    background message or a Stop hook started), and for a Stop after a run
    that the model did not finish.
    """

    context = EventContext(
        host="agy",
        source_event=event.hook_event_name,
        session_id=event.conversation_id,
        transcript_path=event.transcript_path,
        cwd=event.cwd,
        model=event.model,
    )
    match event:
        case agy.events.SessionStartInput():
            # agy fires SessionStart only for a new conversation.
            return SessionStarted(context=context, source="startup")
        case agy.events.PreInvocationInput():
            if event.invocation_num > 0 or not _answers_user_input(
                Path(event.transcript_path), event.initial_num_steps
            ):
                return None
            return PromptSubmitted(context=context, prompt=event.last_user_input)
        case agy.events.PreToolUseInput():
            return ToolCallProposed(
                context=context,
                tool_name=event.tool_call.name,
                tool_input=event.tool_call.args,
                tool_use_id=event.tool_call.id,
            )
        case agy.events.PostToolUseInput():
            if event.error:
                return ToolCallFailed(
                    context=context,
                    tool_name=event.tool_call.name,
                    tool_input=event.tool_call.args,
                    tool_use_id=event.tool_call.id,
                    error=event.error,
                )
            return ToolCallCompleted(
                context=context,
                tool_name=event.tool_call.name,
                tool_input=event.tool_call.args,
                tool_response=None,
                tool_use_id=event.tool_call.id,
            )
        case agy.events.StopInput():
            # Claude Code and Codex stop a turn for their Stop hook only when the
            # model finished; a Stop hook must not continue a turn that the user
            # cancelled, that failed, or that a hook ended (a refused prompt).
            if event.termination_reason in AGY_UNFINISHED:
                return None
            if event.termination_reason not in AGY_FINISHED:
                raise ValueError(f"unknown agy terminationReason {event.termination_reason!r}")
            return TurnStopped(
                context=context,
                stop_hook_active=event.continuation_active or event.execution_num > 0,
                last_assistant_message=None,
            )
    raise AssertionError(f"unmapped agy event type: {type(event).__name__}")
