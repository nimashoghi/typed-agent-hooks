"""Translate shared result intents into strict agy output models.

agy can carry less than Codex and Claude Code. It adds context only at session
start and before a model call, it shows no informational hook message to the
user, and it can end a turn early only as an error. A result whose intent agy
cannot carry raises ``SharedOutputError``. The one exception is the
informational ``system_message`` of a result whose main intent agy carries: it
is left out, and the converter returns a note that says so, which ``main()``
writes to stderr after the output.
"""

from typed_agent_hooks import agy

from .events import AnyEvent
from .outputs import (
    BLOCK_EVENTS,
    CONTEXT_EVENTS,
    MESSAGE_EVENTS,
    PERMISSION_EVENTS,
    STOP_EVENTS,
    TOOL_DECISION_EVENTS,
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
    require_event,
)

Converted = tuple[agy.outputs.HookResult, list[str]]


def _unsupported(event: AnyEvent, output: object, why: str) -> SharedOutputError:
    return SharedOutputError(
        f"{type(output).__name__} is not supported by agy on {event.event_name} "
        f"(agy {event.context.source_event}): {why}"
    )


def _omitted(event: AnyEvent, output: AddContext | Block | AllowTool | DenyTool) -> list[str]:
    """The note for a system_message that agy cannot show, if the result has one."""
    if output.system_message is None:
        return []
    return [
        f"agy left out the system_message of {type(output).__name__} on {event.event_name}: "
        "agy shows no informational hook message to the user"
    ]


def _context(event: AnyEvent, output: AddContext) -> Converted:
    step = agy.outputs.SystemMessageItem(
        system_message=agy.outputs.SystemMessageStep(system_message=output.text)
    )
    match event.event_name:
        case "SessionStarted":
            return agy.outputs.SessionStartOutput(inject_steps=[step]), _omitted(event, output)
        case "PromptSubmitted":
            return agy.outputs.PreInvocationOutput(inject_steps=[step]), _omitted(event, output)
    raise _unsupported(event, output, "agy adds context only at session start and before a prompt")


def _tool_decision(event: AnyEvent, output: AllowTool | DenyTool) -> Converted:
    require_event(event, TOOL_DECISION_EVENTS, output)
    if output.context is not None:
        raise _unsupported(event, output, "agy PreToolUse cannot add context")
    if isinstance(output, DenyTool):
        denied = agy.outputs.PreToolUseOutput(decision="deny", reason=output.reason)
        return denied, _omitted(event, output)
    overwrite = output.updated_input
    if overwrite is not None:
        assert event.event_name == "ToolCallProposed"
        if not isinstance(overwrite, dict):
            raise _unsupported(event, output, "agy rewrites only object tool arguments")
        # agy merges the overwrite into the arguments that it sent, so a removed
        # argument would stay. HookApp gives the handler a copy of the event, so
        # event.tool_input holds those arguments.
        assert isinstance(event.tool_input, dict)
        if missing := sorted(set(event.tool_input) - set(overwrite)):
            raise _unsupported(
                event, output, f"agy cannot remove tool arguments {', '.join(missing)}"
            )
    allowed = agy.outputs.PreToolUseOutput(
        decision="allow", reason=output.reason, overwrite=overwrite
    )
    return allowed, _omitted(event, output)


def to_agy_output(event: AnyEvent, output: Result) -> Converted:
    """Convert a shared result into a strict agy output model, with a note for
    each field that agy leaves out."""

    match output:
        case None:
            return None, []
        case SystemMessage():
            require_event(event, MESSAGE_EVENTS, output)
            raise _unsupported(event, output, "agy shows no informational hook message to the user")
        case AddContext():
            require_event(event, CONTEXT_EVENTS, output)
            return _context(event, output)
        case Block():
            require_event(event, BLOCK_EVENTS, output)
            if not output.reason:
                raise SharedOutputError("Block needs a reason")
            if event.event_name == "PromptSubmitted":
                # agy has already added the prompt to the conversation. Ending
                # the run before the model call shows the reason as an error.
                error = agy.outputs.ErrorMessageStep(user_message=output.reason)
                refused = agy.outputs.PreInvocationOutput(
                    inject_steps=[agy.outputs.ErrorMessageItem(error_message=error)],
                    termination_behavior="terminate",
                )
                return refused, _omitted(event, output)
            if event.event_name == "TurnStopped":
                continued = agy.outputs.StopOutput(decision="continue", reason=output.reason)
                return continued, _omitted(event, output)
            raise AssertionError(f"unhandled block event {event.event_name}")
        case Stop():
            require_event(event, STOP_EVENTS, output)
            if event.event_name == "TurnStopped":
                raise _unsupported(
                    event, output, "agy shows no reason for a stop; return None to let it stop"
                )
            raise _unsupported(
                event,
                output,
                "agy ends a turn early only as an error; use Block to refuse a prompt",
            )
        case AllowTool() | DenyTool():
            return _tool_decision(event, output)
        case AllowPermission() | DenyPermission():
            # agy has no permission-request event, so this always raises.
            require_event(event, PERMISSION_EVENTS, output)
    raise AssertionError(f"unhandled shared output {type(output).__name__} on {event.event_name}")
