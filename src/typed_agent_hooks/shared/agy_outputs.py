"""Translate shared result intents into strict agy output models.

agy can carry less than Codex and Claude Code. It adds context only at session
start and before a model call, and its PostToolUse output is empty. A result
that is valid for an event in the shared table but that agy cannot carry raises
``SharedOutputError``.
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


def _unsupported(event: AnyEvent, output: object, why: str) -> SharedOutputError:
    return SharedOutputError(
        f"{type(output).__name__} is not supported by agy on {event.event_name} "
        f"(agy {event.context.source_event}): {why}"
    )


def _steps(
    *, context: str | None = None, user_message: str | None = None, error: str | None = None
) -> list[agy.outputs.InjectStep]:
    steps = []
    if error is not None:
        steps.append(
            agy.outputs.InjectStep(error_message=agy.outputs.ErrorMessageStep(user_message=error))
        )
    if context is not None:
        steps.append(
            agy.outputs.InjectStep(
                system_message=agy.outputs.SystemMessageStep(system_message=context)
            )
        )
    if user_message is not None:
        # An empty systemMessage sends the model nothing; agy shows the
        # metadata Markdown to the user.
        metadata = agy.outputs.SystemMessageMetadata(user_markdown=user_message)
        step = agy.outputs.SystemMessageStep(system_message="", metadata=metadata)
        steps.append(agy.outputs.InjectStep(system_message=step))
    return steps


def _inject(
    event: AnyEvent, output: object, steps: list[agy.outputs.InjectStep]
) -> agy.outputs.StructuredOutput:
    match event.event_name:
        case "SessionStarted":
            return agy.outputs.SessionStartOutput(inject_steps=steps)
        case "PromptSubmitted":
            return agy.outputs.PreInvocationOutput(inject_steps=steps)
    raise _unsupported(
        event, output, "agy adds steps only at session start and before a model call"
    )


def _end_prompt(event: AnyEvent, output: Block | Stop) -> agy.outputs.PreInvocationOutput:
    # agy has already added the prompt to the conversation. Terminating ends
    # the turn before the model call and shows the reason to the user only.
    steps = _steps(error=output.reason, user_message=output.system_message)
    return agy.outputs.PreInvocationOutput(inject_steps=steps, termination_behavior="terminate")


def _tool_decision(event: AnyEvent, output: AllowTool | DenyTool) -> agy.outputs.PreToolUseOutput:
    require_event(event, TOOL_DECISION_EVENTS, output)
    if output.context is not None:
        raise _unsupported(event, output, "agy PreToolUse cannot add context")
    if output.system_message is not None:
        raise _unsupported(event, output, "agy PreToolUse cannot show a system message")
    if isinstance(output, DenyTool):
        return agy.outputs.PreToolUseOutput(decision="deny", reason=output.reason)
    overwrite = output.updated_input
    if overwrite is not None:
        assert event.event_name == "ToolCallProposed"
        current = event.tool_input
        if not isinstance(overwrite, dict) or not isinstance(current, dict):
            raise _unsupported(event, output, "agy rewrites only object tool arguments")
        # agy merges the overwrite into the arguments, so a removed key would stay.
        if missing := sorted(set(current) - set(overwrite)):
            raise _unsupported(
                event, output, f"agy cannot remove tool arguments {', '.join(missing)}"
            )
    return agy.outputs.PreToolUseOutput(decision="allow", reason=output.reason, overwrite=overwrite)


def to_agy_output(event: AnyEvent, output: Result) -> agy.outputs.HookResult:
    """Convert a shared result into a strict agy output model."""

    match output:
        case None:
            return None
        case SystemMessage(message=message):
            require_event(event, MESSAGE_EVENTS, output)
            return _inject(event, output, _steps(user_message=message))
        case AddContext():
            require_event(event, CONTEXT_EVENTS, output)
            steps = _steps(context=output.text, user_message=output.system_message)
            return _inject(event, output, steps)
        case Block():
            require_event(event, BLOCK_EVENTS, output)
            if event.event_name == "PromptSubmitted":
                return _end_prompt(event, output)
            if output.system_message is not None:
                raise _unsupported(event, output, "agy Stop cannot show a system message")
            return agy.outputs.StopOutput(decision="continue", reason=output.reason)
        case Stop():
            require_event(event, STOP_EVENTS, output)
            if event.event_name == "PromptSubmitted":
                return _end_prompt(event, output)
            raise _unsupported(event, output, "agy shows no reason for a turn that stops")
        case AllowTool() | DenyTool():
            return _tool_decision(event, output)
        case AllowPermission() | DenyPermission():
            # agy has no permission-request event, so this always raises.
            require_event(event, PERMISSION_EVENTS, output)
    raise AssertionError(f"unhandled shared output {type(output).__name__} on {event.event_name}")
