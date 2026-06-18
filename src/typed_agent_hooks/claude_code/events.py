"""Strict Claude Code command-hook input schemas."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import Field, TypeAdapter, model_validator

from typed_agent_hooks.core import Json, JsonInput, StrictModel, parse_json_object

ClaudeEventName: TypeAlias = Literal[
    "SessionStart",
    "Setup",
    "InstructionsLoaded",
    "UserPromptSubmit",
    "UserPromptExpansion",
    "MessageDisplay",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "PostToolUseFailure",
    "PostToolBatch",
    "PermissionDenied",
    "Notification",
    "SubagentStart",
    "SubagentStop",
    "TaskCreated",
    "TaskCompleted",
    "Stop",
    "StopFailure",
    "TeammateIdle",
    "ConfigChange",
    "CwdChanged",
    "FileChanged",
    "WorktreeCreate",
    "WorktreeRemove",
    "PreCompact",
    "PostCompact",
    "SessionEnd",
    "Elicitation",
    "ElicitationResult",
]
PermissionMode: TypeAlias = Literal[
    "default", "plan", "acceptEdits", "auto", "dontAsk", "bypassPermissions"
]
EffortLevel: TypeAlias = Literal["low", "medium", "high", "xhigh", "max"]
StartSource: TypeAlias = Literal["startup", "resume", "clear", "compact"]
SetupTrigger: TypeAlias = Literal["init", "maintenance"]
CompactTrigger: TypeAlias = Literal["manual", "auto"]
MemoryType: TypeAlias = Literal["User", "Project", "Local", "Managed"]
LoadReason: TypeAlias = Literal[
    "session_start", "nested_traversal", "path_glob_match", "include", "compact"
]
ExpansionType: TypeAlias = Literal["slash_command", "mcp_prompt"]
NotificationType: TypeAlias = Literal[
    "permission_prompt",
    "idle_prompt",
    "auth_success",
    "elicitation_dialog",
    "elicitation_complete",
    "elicitation_response",
]
ConfigSource: TypeAlias = Literal[
    "user_settings", "project_settings", "local_settings", "policy_settings", "skills"
]
FileEvent: TypeAlias = Literal["change", "add", "unlink"]
SessionEndReason: TypeAlias = Literal[
    "clear", "resume", "logout", "prompt_input_exit", "bypass_permissions_disabled", "other"
]
ElicitationMode: TypeAlias = Literal["form", "url"]
ElicitationAction: TypeAlias = Literal["accept", "decline", "cancel"]
StopFailureError: TypeAlias = Literal[
    "rate_limit",
    "overloaded",
    "authentication_failed",
    "oauth_org_not_allowed",
    "billing_error",
    "invalid_request",
    "model_not_found",
    "server_error",
    "max_output_tokens",
    "unknown",
]


class Effort(StrictModel):
    level: EffortLevel


class BaseInput(StrictModel):
    """Documented common Claude Code command-hook input fields."""

    session_id: str
    transcript_path: str
    cwd: str
    hook_event_name: ClaudeEventName
    permission_mode: PermissionMode | None = None
    effort: Effort | None = None
    agent_id: str | None = None
    agent_type: str | None = None


class PermissionRule(StrictModel):
    tool_name: str = Field(validation_alias="toolName", serialization_alias="toolName")
    rule_content: str | None = Field(
        default=None, validation_alias="ruleContent", serialization_alias="ruleContent"
    )


class RulesPermissionUpdate(StrictModel):
    type: Literal["addRules", "replaceRules", "removeRules"]
    rules: list[PermissionRule]
    behavior: Literal["allow", "deny", "ask"]
    destination: Literal["session", "localSettings", "projectSettings", "userSettings"]


class SetModePermissionUpdate(StrictModel):
    type: Literal["setMode"]
    mode: PermissionMode
    destination: Literal["session", "localSettings", "projectSettings", "userSettings"]


class DirectoryPermissionUpdate(StrictModel):
    type: Literal["addDirectories", "removeDirectories"]
    directories: list[str]
    destination: Literal["session", "localSettings", "projectSettings", "userSettings"]


PermissionUpdate: TypeAlias = Annotated[
    RulesPermissionUpdate | SetModePermissionUpdate | DirectoryPermissionUpdate,
    Field(discriminator="type"),
]


class BackgroundTask(StrictModel):
    id: str
    type: str
    status: str
    description: str
    command: str | None = None
    agent_type: str | None = None
    server: str | None = None
    tool: str | None = None
    name: str | None = None


class SessionCron(StrictModel):
    id: str
    schedule: str
    recurring: bool
    prompt: str


class ToolCall(StrictModel):
    tool_name: str
    tool_input: Json
    tool_use_id: str
    tool_response: Json


class SessionStartInput(BaseInput):
    hook_event_name: Literal["SessionStart"]
    source: StartSource
    model: str | None = None
    session_title: str | None = None


class SetupInput(BaseInput):
    hook_event_name: Literal["Setup"]
    trigger: SetupTrigger


class InstructionsLoadedInput(BaseInput):
    hook_event_name: Literal["InstructionsLoaded"]
    file_path: str
    memory_type: MemoryType
    load_reason: LoadReason
    globs: list[str] | None = None
    trigger_file_path: str | None = None
    parent_file_path: str | None = None


class UserPromptSubmitInput(BaseInput):
    hook_event_name: Literal["UserPromptSubmit"]
    prompt: str


class UserPromptExpansionInput(BaseInput):
    hook_event_name: Literal["UserPromptExpansion"]
    expansion_type: ExpansionType
    command_name: str
    command_args: str
    command_source: str
    prompt: str


class MessageDisplayInput(BaseInput):
    hook_event_name: Literal["MessageDisplay"]
    turn_id: str
    message_id: str
    index: int = Field(ge=0)
    final: bool
    delta: str


class PreToolUseInput(BaseInput):
    hook_event_name: Literal["PreToolUse"]
    tool_name: str
    tool_input: Json
    tool_use_id: str


class PermissionRequestInput(BaseInput):
    hook_event_name: Literal["PermissionRequest"]
    tool_name: str
    tool_input: Json
    permission_suggestions: list[PermissionUpdate] | None = None


class PostToolUseInput(BaseInput):
    hook_event_name: Literal["PostToolUse"]
    tool_name: str
    tool_input: Json
    tool_response: Json
    tool_use_id: str
    duration_ms: int | None = Field(default=None, ge=0)


class PostToolUseFailureInput(BaseInput):
    hook_event_name: Literal["PostToolUseFailure"]
    tool_name: str
    tool_input: Json
    tool_use_id: str
    error: str
    is_interrupt: bool | None = None
    duration_ms: int | None = Field(default=None, ge=0)


class PostToolBatchInput(BaseInput):
    hook_event_name: Literal["PostToolBatch"]
    tool_calls: list[ToolCall]


class PermissionDeniedInput(BaseInput):
    hook_event_name: Literal["PermissionDenied"]
    tool_name: str
    tool_input: Json
    tool_use_id: str
    reason: str


class NotificationInput(BaseInput):
    hook_event_name: Literal["Notification"]
    message: str
    title: str | None = None
    notification_type: NotificationType


class SubagentStartInput(BaseInput):
    hook_event_name: Literal["SubagentStart"]
    agent_id: str
    agent_type: str


class SubagentStopInput(BaseInput):
    hook_event_name: Literal["SubagentStop"]
    stop_hook_active: bool
    agent_id: str
    agent_type: str
    agent_transcript_path: str
    last_assistant_message: str | None
    background_tasks: list[BackgroundTask] | None = None
    session_crons: list[SessionCron] | None = None


class TaskCreatedInput(BaseInput):
    hook_event_name: Literal["TaskCreated"]
    task_id: str
    task_subject: str
    task_description: str | None = None
    teammate_name: str | None = None
    team_name: str | None = None


class TaskCompletedInput(BaseInput):
    hook_event_name: Literal["TaskCompleted"]
    task_id: str
    task_subject: str
    task_description: str | None = None
    teammate_name: str | None = None
    team_name: str | None = None


class StopInput(BaseInput):
    hook_event_name: Literal["Stop"]
    stop_hook_active: bool
    last_assistant_message: str | None
    background_tasks: list[BackgroundTask] | None = None
    session_crons: list[SessionCron] | None = None


class StopFailureInput(BaseInput):
    hook_event_name: Literal["StopFailure"]
    error: StopFailureError
    error_details: str | None = None
    last_assistant_message: str | None = None


class TeammateIdleInput(BaseInput):
    hook_event_name: Literal["TeammateIdle"]
    teammate_name: str
    team_name: str


class ConfigChangeInput(BaseInput):
    hook_event_name: Literal["ConfigChange"]
    source: ConfigSource
    file_path: str | None = None


class CwdChangedInput(BaseInput):
    hook_event_name: Literal["CwdChanged"]
    old_cwd: str
    new_cwd: str


class FileChangedInput(BaseInput):
    hook_event_name: Literal["FileChanged"]
    file_path: str
    event: FileEvent


class WorktreeCreateInput(BaseInput):
    hook_event_name: Literal["WorktreeCreate"]
    name: str


class WorktreeRemoveInput(BaseInput):
    hook_event_name: Literal["WorktreeRemove"]
    worktree_path: str


class PreCompactInput(BaseInput):
    hook_event_name: Literal["PreCompact"]
    trigger: CompactTrigger
    custom_instructions: str


class PostCompactInput(BaseInput):
    hook_event_name: Literal["PostCompact"]
    trigger: CompactTrigger
    compact_summary: str


class SessionEndInput(BaseInput):
    hook_event_name: Literal["SessionEnd"]
    reason: SessionEndReason


class ElicitationInput(BaseInput):
    hook_event_name: Literal["Elicitation"]
    mcp_server_name: str
    message: str
    mode: ElicitationMode | None = None
    url: str | None = None
    elicitation_id: str | None = None
    requested_schema: Json | None = None


class ElicitationResultInput(BaseInput):
    hook_event_name: Literal["ElicitationResult"]
    mcp_server_name: str
    action: ElicitationAction
    mode: ElicitationMode | None = None
    elicitation_id: str | None = None
    content: Json | None = None

    @model_validator(mode="after")
    def _content_requires_accept(self) -> ElicitationResultInput:
        if self.action != "accept" and self.content is not None:
            raise ValueError("ElicitationResult content requires action='accept'")
        return self


AnyInput: TypeAlias = Annotated[
    SessionStartInput
    | SetupInput
    | InstructionsLoadedInput
    | UserPromptSubmitInput
    | UserPromptExpansionInput
    | MessageDisplayInput
    | PreToolUseInput
    | PermissionRequestInput
    | PostToolUseInput
    | PostToolUseFailureInput
    | PostToolBatchInput
    | PermissionDeniedInput
    | NotificationInput
    | SubagentStartInput
    | SubagentStopInput
    | TaskCreatedInput
    | TaskCompletedInput
    | StopInput
    | StopFailureInput
    | TeammateIdleInput
    | ConfigChangeInput
    | CwdChangedInput
    | FileChangedInput
    | WorktreeCreateInput
    | WorktreeRemoveInput
    | PreCompactInput
    | PostCompactInput
    | SessionEndInput
    | ElicitationInput
    | ElicitationResultInput,
    Field(discriminator="hook_event_name"),
]

INPUT_ADAPTER: TypeAdapter[AnyInput] = TypeAdapter(AnyInput)
EVENT_NAMES: tuple[ClaudeEventName, ...] = (
    "SessionStart",
    "Setup",
    "InstructionsLoaded",
    "UserPromptSubmit",
    "UserPromptExpansion",
    "MessageDisplay",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "PostToolUseFailure",
    "PostToolBatch",
    "PermissionDenied",
    "Notification",
    "SubagentStart",
    "SubagentStop",
    "TaskCreated",
    "TaskCompleted",
    "Stop",
    "StopFailure",
    "TeammateIdle",
    "ConfigChange",
    "CwdChanged",
    "FileChanged",
    "WorktreeCreate",
    "WorktreeRemove",
    "PreCompact",
    "PostCompact",
    "SessionEnd",
    "Elicitation",
    "ElicitationResult",
)

EVENT_NAME_BY_TYPE: dict[type[BaseInput], ClaudeEventName] = {
    SessionStartInput: "SessionStart",
    SetupInput: "Setup",
    InstructionsLoadedInput: "InstructionsLoaded",
    UserPromptSubmitInput: "UserPromptSubmit",
    UserPromptExpansionInput: "UserPromptExpansion",
    MessageDisplayInput: "MessageDisplay",
    PreToolUseInput: "PreToolUse",
    PermissionRequestInput: "PermissionRequest",
    PostToolUseInput: "PostToolUse",
    PostToolUseFailureInput: "PostToolUseFailure",
    PostToolBatchInput: "PostToolBatch",
    PermissionDeniedInput: "PermissionDenied",
    NotificationInput: "Notification",
    SubagentStartInput: "SubagentStart",
    SubagentStopInput: "SubagentStop",
    TaskCreatedInput: "TaskCreated",
    TaskCompletedInput: "TaskCompleted",
    StopInput: "Stop",
    StopFailureInput: "StopFailure",
    TeammateIdleInput: "TeammateIdle",
    ConfigChangeInput: "ConfigChange",
    CwdChangedInput: "CwdChanged",
    FileChangedInput: "FileChanged",
    WorktreeCreateInput: "WorktreeCreate",
    WorktreeRemoveInput: "WorktreeRemove",
    PreCompactInput: "PreCompact",
    PostCompactInput: "PostCompact",
    SessionEndInput: "SessionEnd",
    ElicitationInput: "Elicitation",
    ElicitationResultInput: "ElicitationResult",
}


def parse_input(data: JsonInput) -> AnyInput:
    """Strictly parse one Claude Code command-hook input payload."""

    return INPUT_ADAPTER.validate_python(parse_json_object(data))
