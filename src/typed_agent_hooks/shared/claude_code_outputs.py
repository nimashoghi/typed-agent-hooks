"""Translate shared result intents into strict Claude Code output models."""

from __future__ import annotations

from typed_agent_hooks import claude_code

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


def _system_message(event: AnyEvent, message: str) -> claude_code.outputs.StructuredOutput:
    match event.event_name:
        case "SessionStarted":
            return claude_code.outputs.SessionStartOutput(system_message=message)
        case "PromptSubmitted":
            return claude_code.outputs.UserPromptSubmitOutput(system_message=message)
        case "ToolCallProposed":
            return claude_code.outputs.PreToolUseOutput(system_message=message)
        case "PermissionRequested":
            return claude_code.outputs.PermissionRequestOutput(system_message=message)
        case "ToolCallCompleted":
            return claude_code.outputs.PostToolUseOutput(system_message=message)
        case "CompactionStarting":
            return claude_code.outputs.PreCompactOutput(system_message=message)
        case "CompactionFinished":
            return claude_code.outputs.PostCompactOutput(system_message=message)
        case "SubagentStarted":
            return claude_code.outputs.SubagentStartOutput(system_message=message)
        case "SubagentStopped":
            return claude_code.outputs.SubagentStopOutput(system_message=message)
        case "TurnStopped":
            return claude_code.outputs.StopOutput(system_message=message)
    raise AssertionError(f"unhandled shared event {event.event_name}")


def _context(event: AnyEvent, output: AddContext) -> claude_code.outputs.StructuredOutput:
    require_event(event, CONTEXT_EVENTS, output)
    match event.event_name:
        case "SessionStarted":
            session_specific = claude_code.outputs.SessionStartSpecificOutput(
                hook_event_name="SessionStart", additional_context=output.text
            )
            return claude_code.outputs.SessionStartOutput(
                system_message=output.system_message,
                hook_specific_output=session_specific,
            )
        case "PromptSubmitted":
            prompt_specific = claude_code.outputs.UserPromptSubmitSpecificOutput(
                hook_event_name="UserPromptSubmit", additional_context=output.text
            )
            return claude_code.outputs.UserPromptSubmitOutput(
                system_message=output.system_message,
                hook_specific_output=prompt_specific,
            )
        case "ToolCallProposed":
            tool_specific = claude_code.outputs.PreToolUseSpecificOutput(
                hook_event_name="PreToolUse", additional_context=output.text
            )
            return claude_code.outputs.PreToolUseOutput(
                system_message=output.system_message,
                hook_specific_output=tool_specific,
            )
        case "ToolCallCompleted":
            completed_specific = claude_code.outputs.PostToolUseSpecificOutput(
                hook_event_name="PostToolUse", additional_context=output.text
            )
            return claude_code.outputs.PostToolUseOutput(
                system_message=output.system_message,
                hook_specific_output=completed_specific,
            )
        case "SubagentStarted":
            subagent_specific = claude_code.outputs.SubagentStartSpecificOutput(
                hook_event_name="SubagentStart", additional_context=output.text
            )
            return claude_code.outputs.SubagentStartOutput(
                system_message=output.system_message,
                hook_specific_output=subagent_specific,
            )
    raise AssertionError(f"unhandled context event {event.event_name}")


def _block(event: AnyEvent, output: Block) -> claude_code.outputs.StructuredOutput:
    require_event(event, BLOCK_EVENTS, output)
    match event.event_name:
        case "PromptSubmitted":
            prompt_specific = (
                claude_code.outputs.UserPromptSubmitSpecificOutput(
                    hook_event_name="UserPromptSubmit", additional_context=output.context
                )
                if output.context is not None
                else None
            )
            return claude_code.outputs.UserPromptSubmitOutput(
                system_message=output.system_message,
                decision="block",
                reason=output.reason,
                hook_specific_output=prompt_specific,
            )
        case "ToolCallCompleted":
            completed_specific = (
                claude_code.outputs.PostToolUseSpecificOutput(
                    hook_event_name="PostToolUse", additional_context=output.context
                )
                if output.context is not None
                else None
            )
            return claude_code.outputs.PostToolUseOutput(
                system_message=output.system_message,
                decision="block",
                reason=output.reason,
                hook_specific_output=completed_specific,
            )
        case "CompactionStarting":
            if output.context is not None:
                raise SharedOutputError("CompactionStarting block cannot include context")
            return claude_code.outputs.PreCompactOutput(
                system_message=output.system_message,
                decision="block",
                reason=output.reason,
            )
        case "SubagentStopped":
            subagent_specific = (
                claude_code.outputs.SubagentStopSpecificOutput(
                    hook_event_name="SubagentStop", additional_context=output.context
                )
                if output.context is not None
                else None
            )
            return claude_code.outputs.SubagentStopOutput(
                system_message=output.system_message,
                decision="block",
                reason=output.reason,
                hook_specific_output=subagent_specific,
            )
        case "TurnStopped":
            stop_specific = (
                claude_code.outputs.StopSpecificOutput(
                    hook_event_name="Stop", additional_context=output.context
                )
                if output.context is not None
                else None
            )
            return claude_code.outputs.StopOutput(
                system_message=output.system_message,
                decision="block",
                reason=output.reason,
                hook_specific_output=stop_specific,
            )
    raise AssertionError(f"unhandled block event {event.event_name}")


def _tool_decision(
    event: AnyEvent, output: AllowTool | DenyTool
) -> claude_code.outputs.PreToolUseOutput:
    if event.event_name != "ToolCallProposed":
        raise SharedOutputError(f"{type(output).__name__} is only valid for ToolCallProposed")
    if isinstance(output, AllowTool):
        specific = claude_code.outputs.PreToolUseSpecificOutput(
            hook_event_name="PreToolUse",
            permission_decision="allow",
            permission_decision_reason=output.reason,
            updated_input=output.updated_input,
            additional_context=output.context,
        )
    else:
        specific = claude_code.outputs.PreToolUseSpecificOutput(
            hook_event_name="PreToolUse",
            permission_decision="deny",
            permission_decision_reason=output.reason,
            additional_context=output.context,
        )
    return claude_code.outputs.PreToolUseOutput(
        system_message=output.system_message, hook_specific_output=specific
    )


def _permission_decision(
    event: AnyEvent, output: AllowPermission | DenyPermission
) -> claude_code.outputs.PermissionRequestOutput:
    if event.event_name != "PermissionRequested":
        raise SharedOutputError(f"{type(output).__name__} is only valid for PermissionRequested")
    if isinstance(output, AllowPermission):
        decision = claude_code.outputs.PermissionRequestDecision(behavior="allow")
    else:
        decision = claude_code.outputs.PermissionRequestDecision(
            behavior="deny", message=output.reason
        )
    specific = claude_code.outputs.PermissionRequestSpecificOutput(
        hook_event_name="PermissionRequest",
        decision=decision,
    )
    return claude_code.outputs.PermissionRequestOutput(
        system_message=output.system_message,
        hook_specific_output=specific,
    )


def _stop(event: AnyEvent, output: Stop) -> claude_code.outputs.StructuredOutput:
    require_event(event, STOP_EVENTS, output)
    match event.event_name:
        case "SessionStarted":
            return claude_code.outputs.SessionStartOutput(
                system_message=output.system_message,
                continue_=False,
                stop_reason=output.reason,
            )
        case "PromptSubmitted":
            return claude_code.outputs.UserPromptSubmitOutput(
                system_message=output.system_message,
                continue_=False,
                stop_reason=output.reason,
            )
        case "ToolCallCompleted":
            return claude_code.outputs.PostToolUseOutput(
                system_message=output.system_message,
                continue_=False,
                stop_reason=output.reason,
            )
        case "CompactionStarting":
            return claude_code.outputs.PreCompactOutput(
                system_message=output.system_message,
                continue_=False,
                stop_reason=output.reason,
            )
        case "CompactionFinished":
            return claude_code.outputs.PostCompactOutput(
                system_message=output.system_message,
                continue_=False,
                stop_reason=output.reason,
            )
        case "SubagentStopped":
            return claude_code.outputs.SubagentStopOutput(
                system_message=output.system_message,
                continue_=False,
                stop_reason=output.reason,
            )
        case "TurnStopped":
            return claude_code.outputs.StopOutput(
                system_message=output.system_message,
                continue_=False,
                stop_reason=output.reason,
            )
    raise AssertionError(f"unhandled stop event {event.event_name}")


def to_claude_code_output(event: AnyEvent, output: Result) -> claude_code.outputs.HookResult:
    """Convert a shared result into a strict Claude Code output model."""

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
