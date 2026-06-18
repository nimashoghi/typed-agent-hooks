"""Strict Codex command-hook output schemas and event/output validation."""

from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import Field, model_validator

from typed_agent_hooks.core import CommonOutput, Json, PlainTextOutput, StrictModel, render_json

from .events import CodexEventName


class AdditionalContext(StrictModel):
    hook_event_name: Literal[
        "SessionStart",
        "SubagentStart",
        "PreToolUse",
        "PostToolUse",
        "UserPromptSubmit",
    ] = Field(validation_alias="hookEventName", serialization_alias="hookEventName")
    additional_context: str = Field(
        validation_alias="additionalContext", serialization_alias="additionalContext"
    )


class SessionStartOutput(CommonOutput):
    hook_specific_output: AdditionalContext | None = Field(
        default=None,
        validation_alias="hookSpecificOutput",
        serialization_alias="hookSpecificOutput",
    )


class SubagentStartOutput(StrictModel):
    system_message: str | None = Field(
        default=None, validation_alias="systemMessage", serialization_alias="systemMessage"
    )
    hook_specific_output: AdditionalContext | None = Field(
        default=None,
        validation_alias="hookSpecificOutput",
        serialization_alias="hookSpecificOutput",
    )


class PreToolUseDecision(StrictModel):
    hook_event_name: Literal["PreToolUse"] = Field(
        validation_alias="hookEventName", serialization_alias="hookEventName"
    )
    permission_decision: Literal["allow", "deny"] | None = Field(
        default=None,
        validation_alias="permissionDecision",
        serialization_alias="permissionDecision",
    )
    permission_decision_reason: str | None = Field(
        default=None,
        validation_alias="permissionDecisionReason",
        serialization_alias="permissionDecisionReason",
    )
    updated_input: Json | None = Field(
        default=None, validation_alias="updatedInput", serialization_alias="updatedInput"
    )
    additional_context: str | None = Field(
        default=None, validation_alias="additionalContext", serialization_alias="additionalContext"
    )

    @model_validator(mode="after")
    def _updated_input_requires_allow(self) -> PreToolUseDecision:
        if self.updated_input is not None and self.permission_decision != "allow":
            raise ValueError("Codex PreToolUse updatedInput requires permissionDecision='allow'")
        return self


class PreToolUseOutput(StrictModel):
    system_message: str | None = Field(
        default=None, validation_alias="systemMessage", serialization_alias="systemMessage"
    )
    decision: Literal["block"] | None = None
    reason: str | None = None
    hook_specific_output: PreToolUseDecision | None = Field(
        default=None,
        validation_alias="hookSpecificOutput",
        serialization_alias="hookSpecificOutput",
    )

    @model_validator(mode="after")
    def _block_requires_reason(self) -> PreToolUseOutput:
        _validate_block(self.decision, self.reason)
        return self


class PermissionDecision(StrictModel):
    behavior: Literal["allow", "deny"]
    message: str | None = None

    @model_validator(mode="after")
    def _allow_has_no_message(self) -> PermissionDecision:
        if self.behavior == "allow" and self.message is not None:
            raise ValueError("Codex PermissionRequest allow cannot include message")
        return self


class PermissionRequestSpecificOutput(StrictModel):
    hook_event_name: Literal["PermissionRequest"] = Field(
        validation_alias="hookEventName", serialization_alias="hookEventName"
    )
    decision: PermissionDecision


class PermissionRequestOutput(StrictModel):
    system_message: str | None = Field(
        default=None, validation_alias="systemMessage", serialization_alias="systemMessage"
    )
    hook_specific_output: PermissionRequestSpecificOutput | None = Field(
        default=None,
        validation_alias="hookSpecificOutput",
        serialization_alias="hookSpecificOutput",
    )


class PostToolUseSpecificOutput(StrictModel):
    hook_event_name: Literal["PostToolUse"] = Field(
        validation_alias="hookEventName", serialization_alias="hookEventName"
    )
    additional_context: str | None = Field(
        default=None, validation_alias="additionalContext", serialization_alias="additionalContext"
    )


class PostToolUseOutput(StrictModel):
    system_message: str | None = Field(
        default=None, validation_alias="systemMessage", serialization_alias="systemMessage"
    )
    continue_: bool | None = Field(
        default=None, validation_alias="continue", serialization_alias="continue"
    )
    stop_reason: str | None = Field(
        default=None, validation_alias="stopReason", serialization_alias="stopReason"
    )
    decision: Literal["block"] | None = None
    reason: str | None = None
    hook_specific_output: PostToolUseSpecificOutput | None = Field(
        default=None,
        validation_alias="hookSpecificOutput",
        serialization_alias="hookSpecificOutput",
    )

    @model_validator(mode="after")
    def _block_requires_reason(self) -> PostToolUseOutput:
        _validate_block(self.decision, self.reason)
        return self


class LifecycleOutput(CommonOutput):
    """Common output used by compact lifecycle events."""


class UserPromptSubmitSpecificOutput(StrictModel):
    hook_event_name: Literal["UserPromptSubmit"] = Field(
        validation_alias="hookEventName", serialization_alias="hookEventName"
    )
    additional_context: str = Field(
        validation_alias="additionalContext", serialization_alias="additionalContext"
    )


class UserPromptSubmitOutput(CommonOutput):
    decision: Literal["block"] | None = None
    reason: str | None = None
    hook_specific_output: UserPromptSubmitSpecificOutput | None = Field(
        default=None,
        validation_alias="hookSpecificOutput",
        serialization_alias="hookSpecificOutput",
    )

    @model_validator(mode="after")
    def _block_requires_reason(self) -> UserPromptSubmitOutput:
        _validate_block(self.decision, self.reason)
        return self


class StopOutput(CommonOutput):
    decision: Literal["block"] | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _block_requires_reason(self) -> StopOutput:
        _validate_block(self.decision, self.reason)
        return self


def _validate_block(decision: str | None, reason: str | None) -> None:
    if decision == "block" and not reason:
        raise ValueError("reason is required when decision='block'")


StructuredOutput: TypeAlias = (
    SessionStartOutput
    | SubagentStartOutput
    | PreToolUseOutput
    | PermissionRequestOutput
    | PostToolUseOutput
    | LifecycleOutput
    | UserPromptSubmitOutput
    | StopOutput
)
HookResult: TypeAlias = StructuredOutput | PlainTextOutput | None

_OUTPUT_TYPE_BY_EVENT: dict[CodexEventName, type[StructuredOutput]] = {
    "SessionStart": SessionStartOutput,
    "SubagentStart": SubagentStartOutput,
    "PreToolUse": PreToolUseOutput,
    "PermissionRequest": PermissionRequestOutput,
    "PostToolUse": PostToolUseOutput,
    "PreCompact": LifecycleOutput,
    "PostCompact": LifecycleOutput,
    "UserPromptSubmit": UserPromptSubmitOutput,
    "SubagentStop": StopOutput,
    "Stop": StopOutput,
}


def render_output(event_name: CodexEventName, output: HookResult) -> str | None:
    """Render output after verifying it belongs to the handled Codex event."""

    if output is None:
        return None
    if isinstance(output, PlainTextOutput):
        return output.text

    expected = _OUTPUT_TYPE_BY_EVENT[event_name]
    if type(output) is not expected:
        raise TypeError(
            f"{event_name} handler returned {type(output).__name__}; "
            f"expected {expected.__name__}, PlainTextOutput, or None"
        )
    return render_json(output)
