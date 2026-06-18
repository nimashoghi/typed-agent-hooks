"""Translate shared result intents into strict Codex output models."""

from typed_agent_hooks import codex

from .events import AnyEvent
from .results import (
    BLOCK_EVENTS,
    CONTEXT_EVENTS,
    STOP_EVENTS,
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


def _system_message(event: AnyEvent, message: str) -> codex.outputs.StructuredOutput:
    match event.event_name:
        case "SessionStarted":
            return codex.outputs.SessionStartOutput(system_message=message)
        case "PromptSubmitted":
            return codex.outputs.UserPromptSubmitOutput(system_message=message)
        case "ToolCallProposed":
            return codex.outputs.PreToolUseOutput(system_message=message)
        case "PermissionRequested":
            return codex.outputs.PermissionRequestOutput(system_message=message)
        case "ToolCallCompleted":
            return codex.outputs.PostToolUseOutput(system_message=message)
        case "CompactionStarting" | "CompactionFinished":
            return codex.outputs.LifecycleOutput(system_message=message)
        case "SubagentStarted":
            return codex.outputs.SubagentStartOutput(system_message=message)
        case "SubagentStopped" | "TurnStopped":
            return codex.outputs.StopOutput(system_message=message)
    raise AssertionError(f"unhandled shared event {event.event_name}")


def _context(event: AnyEvent, output: AddContext) -> codex.outputs.StructuredOutput:
    require_event(event, CONTEXT_EVENTS, output)
    match event.event_name:
        case "SessionStarted":
            session_specific = codex.outputs.AdditionalContext(
                hook_event_name="SessionStart", additional_context=output.text
            )
            return codex.outputs.SessionStartOutput(
                system_message=output.system_message,
                hook_specific_output=session_specific,
            )
        case "PromptSubmitted":
            prompt_specific = codex.outputs.UserPromptSubmitSpecificOutput(
                hook_event_name="UserPromptSubmit", additional_context=output.text
            )
            return codex.outputs.UserPromptSubmitOutput(
                system_message=output.system_message,
                hook_specific_output=prompt_specific,
            )
        case "ToolCallProposed":
            tool_specific = codex.outputs.PreToolUseDecision(
                hook_event_name="PreToolUse", additional_context=output.text
            )
            return codex.outputs.PreToolUseOutput(
                system_message=output.system_message,
                hook_specific_output=tool_specific,
            )
        case "ToolCallCompleted":
            completed_specific = codex.outputs.PostToolUseSpecificOutput(
                hook_event_name="PostToolUse", additional_context=output.text
            )
            return codex.outputs.PostToolUseOutput(
                system_message=output.system_message,
                hook_specific_output=completed_specific,
            )
        case "SubagentStarted":
            subagent_specific = codex.outputs.AdditionalContext(
                hook_event_name="SubagentStart", additional_context=output.text
            )
            return codex.outputs.SubagentStartOutput(
                system_message=output.system_message,
                hook_specific_output=subagent_specific,
            )
    raise AssertionError(f"unhandled context event {event.event_name}")


def _block(event: AnyEvent, output: Block) -> codex.outputs.StructuredOutput:
    require_event(event, BLOCK_EVENTS, output)
    match event.event_name:
        case "PromptSubmitted":
            prompt_specific = (
                codex.outputs.UserPromptSubmitSpecificOutput(
                    hook_event_name="UserPromptSubmit", additional_context=output.context
                )
                if output.context is not None
                else None
            )
            return codex.outputs.UserPromptSubmitOutput(
                system_message=output.system_message,
                decision="block",
                reason=output.reason,
                hook_specific_output=prompt_specific,
            )
        case "ToolCallCompleted":
            completed_specific = (
                codex.outputs.PostToolUseSpecificOutput(
                    hook_event_name="PostToolUse", additional_context=output.context
                )
                if output.context is not None
                else None
            )
            return codex.outputs.PostToolUseOutput(
                system_message=output.system_message,
                decision="block",
                reason=output.reason,
                hook_specific_output=completed_specific,
            )
        case "CompactionStarting":
            if output.context is not None:
                raise SharedOutputError("CompactionStarting block cannot include context")
            return codex.outputs.LifecycleOutput(
                system_message=output.system_message,
                continue_=False,
                stop_reason=output.reason,
            )
        case "SubagentStopped" | "TurnStopped":
            if output.context is not None:
                raise SharedOutputError(f"Codex {event.event_name} block cannot include context")
            return codex.outputs.StopOutput(
                system_message=output.system_message,
                decision="block",
                reason=output.reason,
            )
    raise AssertionError(f"unhandled block event {event.event_name}")


def _tool_decision(event: AnyEvent, output: AllowTool | DenyTool) -> codex.outputs.PreToolUseOutput:
    if event.event_name != "ToolCallProposed":
        raise SharedOutputError(f"{type(output).__name__} is only valid for ToolCallProposed")
    if isinstance(output, AllowTool):
        specific = codex.outputs.PreToolUseDecision(
            hook_event_name="PreToolUse",
            permission_decision="allow",
            permission_decision_reason=output.reason,
            updated_input=output.updated_input,
            additional_context=output.context,
        )
    else:
        specific = codex.outputs.PreToolUseDecision(
            hook_event_name="PreToolUse",
            permission_decision="deny",
            permission_decision_reason=output.reason,
            additional_context=output.context,
        )
    return codex.outputs.PreToolUseOutput(
        system_message=output.system_message, hook_specific_output=specific
    )


def _permission_decision(
    event: AnyEvent, output: AllowPermission | DenyPermission
) -> codex.outputs.PermissionRequestOutput:
    if event.event_name != "PermissionRequested":
        raise SharedOutputError(f"{type(output).__name__} is only valid for PermissionRequested")
    if isinstance(output, AllowPermission):
        decision = codex.outputs.PermissionDecision(behavior="allow")
    else:
        decision = codex.outputs.PermissionDecision(behavior="deny", message=output.reason)
    specific = codex.outputs.PermissionRequestSpecificOutput(
        hook_event_name="PermissionRequest",
        decision=decision,
    )
    return codex.outputs.PermissionRequestOutput(
        system_message=output.system_message,
        hook_specific_output=specific,
    )


def _stop(event: AnyEvent, output: Stop) -> codex.outputs.StructuredOutput:
    require_event(event, STOP_EVENTS, output)
    match event.event_name:
        case "SessionStarted":
            return codex.outputs.SessionStartOutput(
                system_message=output.system_message,
                continue_=False,
                stop_reason=output.reason,
            )
        case "PromptSubmitted":
            return codex.outputs.UserPromptSubmitOutput(
                system_message=output.system_message,
                continue_=False,
                stop_reason=output.reason,
            )
        case "ToolCallCompleted":
            return codex.outputs.PostToolUseOutput(
                system_message=output.system_message,
                continue_=False,
                stop_reason=output.reason,
            )
        case "CompactionStarting" | "CompactionFinished":
            return codex.outputs.LifecycleOutput(
                system_message=output.system_message,
                continue_=False,
                stop_reason=output.reason,
            )
        case "SubagentStopped" | "TurnStopped":
            return codex.outputs.StopOutput(
                system_message=output.system_message,
                continue_=False,
                stop_reason=output.reason,
            )
    raise AssertionError(f"unhandled stop event {event.event_name}")


def to_codex_output(event: AnyEvent, output: Result) -> codex.outputs.HookResult:
    """Convert a shared result into a strict Codex output model."""

    match output:
        case None:
            return None
        case SystemMessage(message=message):
            return _system_message(event, message)
        case AddContext():
            return _context(event, output)
        case Block():
            return _block(event, output)
        case AllowTool() | DenyTool():
            return _tool_decision(event, output)
        case AllowPermission() | DenyPermission():
            return _permission_decision(event, output)
        case Stop():
            return _stop(event, output)
    raise AssertionError(f"unknown shared output type {type(output).__name__}")
