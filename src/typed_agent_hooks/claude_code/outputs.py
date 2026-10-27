"""Strict Claude Code command-hook output schemas."""

from typing import Literal, TypeAlias

from pydantic import Field

from typed_agent_hooks.core import BlockableOutput, CommonOutput, Json, StrictModel


class SessionStartSpecificOutput(StrictModel):
    hook_event_name: Literal["SessionStart"] = Field(serialization_alias="hookEventName")
    additional_context: str = Field(serialization_alias="additionalContext")


class SessionStartOutput(CommonOutput):
    hook_specific_output: SessionStartSpecificOutput | None = Field(
        default=None,
        serialization_alias="hookSpecificOutput",
    )


class UserPromptSubmitSpecificOutput(StrictModel):
    hook_event_name: Literal["UserPromptSubmit"] = Field(serialization_alias="hookEventName")
    additional_context: str = Field(serialization_alias="additionalContext")


class UserPromptSubmitOutput(BlockableOutput):
    hook_specific_output: UserPromptSubmitSpecificOutput | None = Field(
        default=None,
        serialization_alias="hookSpecificOutput",
    )


class PreToolUseSpecificOutput(StrictModel):
    hook_event_name: Literal["PreToolUse"] = Field(serialization_alias="hookEventName")
    permission_decision: Literal["allow", "deny"] | None = Field(
        default=None,
        serialization_alias="permissionDecision",
    )
    permission_decision_reason: str | None = Field(
        default=None,
        serialization_alias="permissionDecisionReason",
    )
    updated_input: Json | None = Field(default=None, serialization_alias="updatedInput")
    additional_context: str | None = Field(default=None, serialization_alias="additionalContext")


class PreToolUseOutput(CommonOutput):
    hook_specific_output: PreToolUseSpecificOutput | None = Field(
        default=None,
        serialization_alias="hookSpecificOutput",
    )


class PermissionRequestDecision(StrictModel):
    behavior: Literal["allow", "deny"]
    message: str | None = None


class PermissionRequestSpecificOutput(StrictModel):
    hook_event_name: Literal["PermissionRequest"] = Field(serialization_alias="hookEventName")
    decision: PermissionRequestDecision


class PermissionRequestOutput(CommonOutput):
    hook_specific_output: PermissionRequestSpecificOutput | None = Field(
        default=None,
        serialization_alias="hookSpecificOutput",
    )


class PostToolUseSpecificOutput(StrictModel):
    hook_event_name: Literal["PostToolUse"] = Field(serialization_alias="hookEventName")
    additional_context: str = Field(serialization_alias="additionalContext")


class PostToolUseOutput(CommonOutput):
    hook_specific_output: PostToolUseSpecificOutput | None = Field(
        default=None,
        serialization_alias="hookSpecificOutput",
    )


class PostToolUseFailureSpecificOutput(StrictModel):
    hook_event_name: Literal["PostToolUseFailure"] = Field(serialization_alias="hookEventName")
    additional_context: str = Field(serialization_alias="additionalContext")


class PostToolUseFailureOutput(CommonOutput):
    hook_specific_output: PostToolUseFailureSpecificOutput | None = Field(
        default=None,
        serialization_alias="hookSpecificOutput",
    )


class SubagentStartSpecificOutput(StrictModel):
    hook_event_name: Literal["SubagentStart"] = Field(serialization_alias="hookEventName")
    additional_context: str = Field(serialization_alias="additionalContext")


class SubagentStartOutput(CommonOutput):
    hook_specific_output: SubagentStartSpecificOutput | None = Field(
        default=None,
        serialization_alias="hookSpecificOutput",
    )


class SubagentStopOutput(BlockableOutput):
    """Structured output for ``SubagentStop``."""


class StopOutput(BlockableOutput):
    """Structured output for ``Stop``."""


StructuredOutput: TypeAlias = (
    SessionStartOutput
    | UserPromptSubmitOutput
    | PreToolUseOutput
    | PermissionRequestOutput
    | PostToolUseOutput
    | PostToolUseFailureOutput
    | SubagentStartOutput
    | SubagentStopOutput
    | StopOutput
)
HookResult: TypeAlias = StructuredOutput | None
