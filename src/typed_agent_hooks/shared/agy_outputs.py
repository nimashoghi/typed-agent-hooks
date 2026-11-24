"""Translate shared result intents into strict agy output models.

agy can carry less than Codex and Claude Code. It adds context only at session
start and before a model call, it has no way to show a hook's message to the
user, and it can end a turn early only as an error. A result whose intent agy
cannot carry raises ``SharedOutputError``. The one exception is the
``system_message`` of a result whose main intent agy carries: it is left out
with a ``SharedOutputWarning``, as the README says.
"""

import warnings

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
    SharedOutputWarning,
    Stop,
    SystemMessage,
    require_event,
)


def _unsupported(event: AnyEvent, output: object, why: str) -> SharedOutputError:
    return SharedOutputError(
        f"{type(output).__name__} is not supported by agy on {event.event_name} "
        f"(agy {event.context.source_event}): {why}"
    )


def _omit_message(event: AnyEvent, output: AddContext | Block | AllowTool | DenyTool) -> None:
    if output.system_message is not None:
        warnings.warn(
            f"agy shows no hook message to the user: left out the system_message of "
            f"{type(output).__name__} on {event.event_name}",
            SharedOutputWarning,
            stacklevel=3,
        )


def _context(event: AnyEvent, output: AddContext) -> agy.outputs.StructuredOutput:
    step = agy.outputs.SystemMessageItem(
        system_message=agy.outputs.SystemMessageStep(system_message=output.text)
    )
    match event.event_name:
        case "SessionStarted":
            _omit_message(event, output)
            return agy.outputs.SessionStartOutput(inject_steps=[step])
        case "PromptSubmitted":
            _omit_message(event, output)
            return agy.outputs.PreInvocationOutput(inject_steps=[step])
    raise _unsupported(event, output, "agy adds context only at session start and before a prompt")


def _tool_decision(event: AnyEvent, output: AllowTool | DenyTool) -> agy.outputs.PreToolUseOutput:
    require_event(event, TOOL_DECISION_EVENTS, output)
    if output.context is not None:
        raise _unsupported(event, output, "agy PreToolUse cannot add context")
    _omit_message(event, output)
    if isinstance(output, DenyTool):
        return agy.outputs.PreToolUseOutput(decision="deny", reason=output.reason)
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
    return agy.outputs.PreToolUseOutput(decision="allow", reason=output.reason, overwrite=overwrite)


def to_agy_output(event: AnyEvent, output: Result) -> agy.outputs.HookResult:
    """Convert a shared result into a strict agy output model."""

    match output:
        case None:
            return None
        case SystemMessage():
            require_event(event, MESSAGE_EVENTS, output)
            raise _unsupported(event, output, "agy shows no hook message to the user")
        case AddContext():
            require_event(event, CONTEXT_EVENTS, output)
            return _context(event, output)
        case Block():
            require_event(event, BLOCK_EVENTS, output)
            if not output.reason:
                raise SharedOutputError("Block needs a reason")
            if event.event_name == "PromptSubmitted":
                _omit_message(event, output)
                # agy has already added the prompt to the conversation. Ending
                # the run before the model call shows the reason as an error.
                error = agy.outputs.ErrorMessageStep(user_message=output.reason)
                return agy.outputs.PreInvocationOutput(
                    inject_steps=[agy.outputs.ErrorMessageItem(error_message=error)],
                    termination_behavior="terminate",
                )
            if event.event_name == "TurnStopped":
                _omit_message(event, output)
                return agy.outputs.StopOutput(decision="continue", reason=output.reason)
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
