"""Strict Codex command-hook output schemas."""

from typing import Literal, TypeAlias

from pydantic import Field

from typed_agent_hooks.core import BlockableOutput, CommonOutput, Json, StrictModel


class AdditionalContext(StrictModel):
    hook_event_name: Literal["SessionStart", "SubagentStart"] = Field(
        serialization_alias="hookEventName"
    )
    additional_context: str = Field(serialization_alias="additionalContext")


class SessionStartOutput(CommonOutput):
    hook_specific_output: AdditionalContext | None = Field(
        default=None,
        serialization_alias="hookSpecificOutput",
    )


class SubagentStartOutput(CommonOutput):
    hook_specific_output: AdditionalContext | None = Field(
        default=None,
        serialization_alias="hookSpecificOutput",
    )


class PreToolUseDecision(StrictModel):
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
    hook_specific_output: PreToolUseDecision | None = Field(
        default=None,
        serialization_alias="hookSpecificOutput",
    )


class PermissionDecision(StrictModel):
    behavior: Literal["allow", "deny"]
    message: str | None = None


class PermissionRequestSpecificOutput(StrictModel):
    hook_event_name: Literal["PermissionRequest"] = Field(serialization_alias="hookEventName")
    decision: PermissionDecision


class PermissionRequestOutput(CommonOutput):
    hook_specific_output: PermissionRequestSpecificOutput | None = Field(
        default=None,
        serialization_alias="hookSpecificOutput",
    )


class PostToolUseSpecificOutput(StrictModel):
    hook_event_name: Literal["PostToolUse"] = Field(serialization_alias="hookEventName")
    additional_context: str | None = Field(default=None, serialization_alias="additionalContext")


class PostToolUseOutput(CommonOutput):
    hook_specific_output: PostToolUseSpecificOutput | None = Field(
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


class StopOutput(BlockableOutput):
    """Structured output for ``Stop`` and ``SubagentStop``."""


StructuredOutput: TypeAlias = (
    SessionStartOutput
    | SubagentStartOutput
    | PreToolUseOutput
    | PermissionRequestOutput
    | PostToolUseOutput
    | UserPromptSubmitOutput
    | StopOutput
)
HookResult: TypeAlias = StructuredOutput | None
