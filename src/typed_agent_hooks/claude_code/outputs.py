"""Strict Claude Code command-hook output schemas and event/output validation."""

from typing import Literal, TypeAlias

from pydantic import Field, model_validator

from typed_agent_hooks.core import (
    ClaudeCommonOutput,
    Json,
    PlainTextOutput,
    StrictModel,
    render_json,
)

from .events import ClaudeEventName, ElicitationAction, PermissionUpdate


class _BlockableOutput(ClaudeCommonOutput):
    decision: Literal["block"] | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _block_requires_reason(self) -> "_BlockableOutput":
        if self.decision == "block" and not self.reason:
            raise ValueError("reason is required when decision='block'")
        return self


class SessionStartSpecificOutput(StrictModel):
    hook_event_name: Literal["SessionStart"] = Field(
        validation_alias="hookEventName", serialization_alias="hookEventName"
    )
    additional_context: str | None = Field(
        default=None, validation_alias="additionalContext", serialization_alias="additionalContext"
    )
    initial_user_message: str | None = Field(
        default=None,
        validation_alias="initialUserMessage",
        serialization_alias="initialUserMessage",
    )
    session_title: str | None = Field(
        default=None, validation_alias="sessionTitle", serialization_alias="sessionTitle"
    )
    watch_paths: list[str] | None = Field(
        default=None, validation_alias="watchPaths", serialization_alias="watchPaths"
    )
    reload_skills: bool | None = Field(
        default=None, validation_alias="reloadSkills", serialization_alias="reloadSkills"
    )


class SessionStartOutput(ClaudeCommonOutput):
    hook_specific_output: SessionStartSpecificOutput | None = Field(
        default=None,
        validation_alias="hookSpecificOutput",
        serialization_alias="hookSpecificOutput",
    )


class SetupSpecificOutput(StrictModel):
    hook_event_name: Literal["Setup"] = Field(
        validation_alias="hookEventName", serialization_alias="hookEventName"
    )
    additional_context: str = Field(
        validation_alias="additionalContext", serialization_alias="additionalContext"
    )


class SetupOutput(ClaudeCommonOutput):
    hook_specific_output: SetupSpecificOutput | None = Field(
        default=None,
        validation_alias="hookSpecificOutput",
        serialization_alias="hookSpecificOutput",
    )


class InstructionsLoadedOutput(ClaudeCommonOutput):
    """Structured output for ``InstructionsLoaded``."""


class UserPromptSubmitSpecificOutput(StrictModel):
    hook_event_name: Literal["UserPromptSubmit"] = Field(
        validation_alias="hookEventName", serialization_alias="hookEventName"
    )
    additional_context: str | None = Field(
        default=None, validation_alias="additionalContext", serialization_alias="additionalContext"
    )
    session_title: str | None = Field(
        default=None, validation_alias="sessionTitle", serialization_alias="sessionTitle"
    )
    suppress_original_prompt: bool | None = Field(
        default=None,
        validation_alias="suppressOriginalPrompt",
        serialization_alias="suppressOriginalPrompt",
    )


class UserPromptSubmitOutput(_BlockableOutput):
    hook_specific_output: UserPromptSubmitSpecificOutput | None = Field(
        default=None,
        validation_alias="hookSpecificOutput",
        serialization_alias="hookSpecificOutput",
    )


class UserPromptExpansionSpecificOutput(StrictModel):
    hook_event_name: Literal["UserPromptExpansion"] = Field(
        validation_alias="hookEventName", serialization_alias="hookEventName"
    )
    additional_context: str | None = Field(
        default=None, validation_alias="additionalContext", serialization_alias="additionalContext"
    )


class UserPromptExpansionOutput(_BlockableOutput):
    hook_specific_output: UserPromptExpansionSpecificOutput | None = Field(
        default=None,
        validation_alias="hookSpecificOutput",
        serialization_alias="hookSpecificOutput",
    )


class MessageDisplaySpecificOutput(StrictModel):
    hook_event_name: Literal["MessageDisplay"] = Field(
        validation_alias="hookEventName", serialization_alias="hookEventName"
    )
    display_content: str | None = Field(
        default=None, validation_alias="displayContent", serialization_alias="displayContent"
    )


class MessageDisplayOutput(ClaudeCommonOutput):
    hook_specific_output: MessageDisplaySpecificOutput | None = Field(
        default=None,
        validation_alias="hookSpecificOutput",
        serialization_alias="hookSpecificOutput",
    )


class PreToolUseSpecificOutput(StrictModel):
    hook_event_name: Literal["PreToolUse"] = Field(
        validation_alias="hookEventName", serialization_alias="hookEventName"
    )
    permission_decision: Literal["allow", "deny", "ask", "defer"] | None = Field(
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
    def _updated_input_requires_allow_or_ask(self) -> "PreToolUseSpecificOutput":
        if self.updated_input is not None and self.permission_decision not in {"allow", "ask"}:
            raise ValueError("updatedInput is only valid for allow/ask")
        return self


class PreToolUseOutput(ClaudeCommonOutput):
    hook_specific_output: PreToolUseSpecificOutput | None = Field(
        default=None,
        validation_alias="hookSpecificOutput",
        serialization_alias="hookSpecificOutput",
    )


class PermissionRequestDecision(StrictModel):
    behavior: Literal["allow", "deny"]
    updated_input: Json | None = Field(
        default=None, validation_alias="updatedInput", serialization_alias="updatedInput"
    )
    updated_permissions: list[PermissionUpdate] | None = Field(
        default=None,
        validation_alias="updatedPermissions",
        serialization_alias="updatedPermissions",
    )
    message: str | None = None
    interrupt: bool | None = None

    @model_validator(mode="after")
    def _behavior_fields_are_consistent(self) -> "PermissionRequestDecision":
        if self.behavior == "allow":
            if self.message is not None or self.interrupt is not None:
                raise ValueError("allow cannot include message or interrupt")
            return self
        if self.updated_input is not None or self.updated_permissions is not None:
            raise ValueError("deny cannot include updatedInput or updatedPermissions")
        return self


class PermissionRequestSpecificOutput(StrictModel):
    hook_event_name: Literal["PermissionRequest"] = Field(
        validation_alias="hookEventName", serialization_alias="hookEventName"
    )
    decision: PermissionRequestDecision


class PermissionRequestOutput(ClaudeCommonOutput):
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
    updated_tool_output: Json | None = Field(
        default=None, validation_alias="updatedToolOutput", serialization_alias="updatedToolOutput"
    )
    updated_mcp_tool_output: Json | None = Field(
        default=None,
        validation_alias="updatedMCPToolOutput",
        serialization_alias="updatedMCPToolOutput",
    )


class PostToolUseOutput(_BlockableOutput):
    hook_specific_output: PostToolUseSpecificOutput | None = Field(
        default=None,
        validation_alias="hookSpecificOutput",
        serialization_alias="hookSpecificOutput",
    )


class PostToolUseFailureSpecificOutput(StrictModel):
    hook_event_name: Literal["PostToolUseFailure"] = Field(
        validation_alias="hookEventName", serialization_alias="hookEventName"
    )
    additional_context: str = Field(
        validation_alias="additionalContext", serialization_alias="additionalContext"
    )


class PostToolUseFailureOutput(ClaudeCommonOutput):
    hook_specific_output: PostToolUseFailureSpecificOutput | None = Field(
        default=None,
        validation_alias="hookSpecificOutput",
        serialization_alias="hookSpecificOutput",
    )


class PostToolBatchSpecificOutput(StrictModel):
    hook_event_name: Literal["PostToolBatch"] = Field(
        validation_alias="hookEventName", serialization_alias="hookEventName"
    )
    additional_context: str | None = Field(
        default=None, validation_alias="additionalContext", serialization_alias="additionalContext"
    )


class PostToolBatchOutput(_BlockableOutput):
    hook_specific_output: PostToolBatchSpecificOutput | None = Field(
        default=None,
        validation_alias="hookSpecificOutput",
        serialization_alias="hookSpecificOutput",
    )


class PermissionDeniedSpecificOutput(StrictModel):
    hook_event_name: Literal["PermissionDenied"] = Field(
        validation_alias="hookEventName", serialization_alias="hookEventName"
    )
    retry: bool


class PermissionDeniedOutput(ClaudeCommonOutput):
    hook_specific_output: PermissionDeniedSpecificOutput | None = Field(
        default=None,
        validation_alias="hookSpecificOutput",
        serialization_alias="hookSpecificOutput",
    )


class NotificationOutput(ClaudeCommonOutput):
    """Structured output for ``Notification``."""


class SubagentStartSpecificOutput(StrictModel):
    hook_event_name: Literal["SubagentStart"] = Field(
        validation_alias="hookEventName", serialization_alias="hookEventName"
    )
    additional_context: str = Field(
        validation_alias="additionalContext", serialization_alias="additionalContext"
    )


class SubagentStartOutput(ClaudeCommonOutput):
    hook_specific_output: SubagentStartSpecificOutput | None = Field(
        default=None,
        validation_alias="hookSpecificOutput",
        serialization_alias="hookSpecificOutput",
    )


class SubagentStopSpecificOutput(StrictModel):
    hook_event_name: Literal["SubagentStop"] = Field(
        validation_alias="hookEventName", serialization_alias="hookEventName"
    )
    additional_context: str = Field(
        validation_alias="additionalContext", serialization_alias="additionalContext"
    )


class SubagentStopOutput(_BlockableOutput):
    hook_specific_output: SubagentStopSpecificOutput | None = Field(
        default=None,
        validation_alias="hookSpecificOutput",
        serialization_alias="hookSpecificOutput",
    )


class TaskCreatedOutput(ClaudeCommonOutput):
    """Structured output for ``TaskCreated``."""


class TaskCompletedOutput(ClaudeCommonOutput):
    """Structured output for ``TaskCompleted``."""


class StopSpecificOutput(StrictModel):
    hook_event_name: Literal["Stop"] = Field(
        validation_alias="hookEventName", serialization_alias="hookEventName"
    )
    additional_context: str = Field(
        validation_alias="additionalContext", serialization_alias="additionalContext"
    )


class StopOutput(_BlockableOutput):
    hook_specific_output: StopSpecificOutput | None = Field(
        default=None,
        validation_alias="hookSpecificOutput",
        serialization_alias="hookSpecificOutput",
    )


class StopFailureOutput(ClaudeCommonOutput):
    """Claude ignores this event's stdout and exit code."""


class TeammateIdleOutput(ClaudeCommonOutput):
    """Structured output for ``TeammateIdle``."""


class ConfigChangeOutput(_BlockableOutput):
    """Structured output for ``ConfigChange``."""


class CwdChangedSpecificOutput(StrictModel):
    hook_event_name: Literal["CwdChanged"] = Field(
        validation_alias="hookEventName", serialization_alias="hookEventName"
    )
    watch_paths: list[str] = Field(validation_alias="watchPaths", serialization_alias="watchPaths")


class CwdChangedOutput(ClaudeCommonOutput):
    hook_specific_output: CwdChangedSpecificOutput | None = Field(
        default=None,
        validation_alias="hookSpecificOutput",
        serialization_alias="hookSpecificOutput",
    )


class FileChangedSpecificOutput(StrictModel):
    hook_event_name: Literal["FileChanged"] = Field(
        validation_alias="hookEventName", serialization_alias="hookEventName"
    )
    watch_paths: list[str] = Field(validation_alias="watchPaths", serialization_alias="watchPaths")


class FileChangedOutput(ClaudeCommonOutput):
    hook_specific_output: FileChangedSpecificOutput | None = Field(
        default=None,
        validation_alias="hookSpecificOutput",
        serialization_alias="hookSpecificOutput",
    )


class WorktreePathOutput(StrictModel):
    """Plain path stdout required by a command ``WorktreeCreate`` hook."""

    path: str = Field(min_length=1)


class WorktreeRemoveOutput(ClaudeCommonOutput):
    """Structured output for ``WorktreeRemove``."""


class PreCompactOutput(_BlockableOutput):
    """Structured output for ``PreCompact``."""


class PostCompactOutput(ClaudeCommonOutput):
    """Structured output for ``PostCompact``."""


class SessionEndOutput(ClaudeCommonOutput):
    """Structured output for ``SessionEnd``."""


class ElicitationSpecificOutput(StrictModel):
    hook_event_name: Literal["Elicitation"] = Field(
        validation_alias="hookEventName", serialization_alias="hookEventName"
    )
    action: ElicitationAction
    content: dict[str, Json] | None = None

    @model_validator(mode="after")
    def _content_requires_accept(self) -> "ElicitationSpecificOutput":
        if self.action != "accept" and self.content is not None:
            raise ValueError("content is only meaningful with action='accept'")
        return self


class ElicitationOutput(ClaudeCommonOutput):
    hook_specific_output: ElicitationSpecificOutput | None = Field(
        default=None,
        validation_alias="hookSpecificOutput",
        serialization_alias="hookSpecificOutput",
    )


class ElicitationResultSpecificOutput(StrictModel):
    hook_event_name: Literal["ElicitationResult"] = Field(
        validation_alias="hookEventName", serialization_alias="hookEventName"
    )
    action: ElicitationAction
    content: dict[str, Json] | None = None

    @model_validator(mode="after")
    def _content_requires_accept(self) -> "ElicitationResultSpecificOutput":
        if self.action != "accept" and self.content is not None:
            raise ValueError("content is only meaningful with action='accept'")
        return self


class ElicitationResultOutput(ClaudeCommonOutput):
    hook_specific_output: ElicitationResultSpecificOutput | None = Field(
        default=None,
        validation_alias="hookSpecificOutput",
        serialization_alias="hookSpecificOutput",
    )


StructuredOutput: TypeAlias = (
    SessionStartOutput
    | SetupOutput
    | InstructionsLoadedOutput
    | UserPromptSubmitOutput
    | UserPromptExpansionOutput
    | MessageDisplayOutput
    | PreToolUseOutput
    | PermissionRequestOutput
    | PostToolUseOutput
    | PostToolUseFailureOutput
    | PostToolBatchOutput
    | PermissionDeniedOutput
    | NotificationOutput
    | SubagentStartOutput
    | SubagentStopOutput
    | TaskCreatedOutput
    | TaskCompletedOutput
    | StopOutput
    | StopFailureOutput
    | TeammateIdleOutput
    | ConfigChangeOutput
    | CwdChangedOutput
    | FileChangedOutput
    | WorktreeRemoveOutput
    | PreCompactOutput
    | PostCompactOutput
    | SessionEndOutput
    | ElicitationOutput
    | ElicitationResultOutput
)
HookResult: TypeAlias = StructuredOutput | PlainTextOutput | WorktreePathOutput | None

_OUTPUT_TYPE_BY_EVENT: dict[ClaudeEventName, type[StrictModel]] = {
    "SessionStart": SessionStartOutput,
    "Setup": SetupOutput,
    "InstructionsLoaded": InstructionsLoadedOutput,
    "UserPromptSubmit": UserPromptSubmitOutput,
    "UserPromptExpansion": UserPromptExpansionOutput,
    "MessageDisplay": MessageDisplayOutput,
    "PreToolUse": PreToolUseOutput,
    "PermissionRequest": PermissionRequestOutput,
    "PostToolUse": PostToolUseOutput,
    "PostToolUseFailure": PostToolUseFailureOutput,
    "PostToolBatch": PostToolBatchOutput,
    "PermissionDenied": PermissionDeniedOutput,
    "Notification": NotificationOutput,
    "SubagentStart": SubagentStartOutput,
    "SubagentStop": SubagentStopOutput,
    "TaskCreated": TaskCreatedOutput,
    "TaskCompleted": TaskCompletedOutput,
    "Stop": StopOutput,
    "StopFailure": StopFailureOutput,
    "TeammateIdle": TeammateIdleOutput,
    "ConfigChange": ConfigChangeOutput,
    "CwdChanged": CwdChangedOutput,
    "FileChanged": FileChangedOutput,
    "WorktreeRemove": WorktreeRemoveOutput,
    "PreCompact": PreCompactOutput,
    "PostCompact": PostCompactOutput,
    "SessionEnd": SessionEndOutput,
    "Elicitation": ElicitationOutput,
    "ElicitationResult": ElicitationResultOutput,
}


def render_output(event_name: ClaudeEventName, output: HookResult) -> str | None:
    """Render output after verifying it belongs to the handled Claude Code event."""

    if output is None:
        return None
    if event_name == "WorktreeCreate":
        if not isinstance(output, WorktreePathOutput):
            raise TypeError("WorktreeCreate handler must return WorktreePathOutput or None")
        return output.path
    if isinstance(output, WorktreePathOutput):
        raise TypeError("WorktreePathOutput is only valid for WorktreeCreate")
    if isinstance(output, PlainTextOutput):
        return output.text

    expected = _OUTPUT_TYPE_BY_EVENT[event_name]
    if type(output) is not expected:
        raise TypeError(
            f"{event_name} handler returned {type(output).__name__}; "
            f"expected {expected.__name__}, PlainTextOutput, or None"
        )
    return render_json(output)
