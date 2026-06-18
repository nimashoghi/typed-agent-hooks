"""Strict Codex command-hook input schemas."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import Field, TypeAdapter

from typed_agent_hooks.core import Json, JsonInput, StrictModel, parse_json_object

CodexEventName: TypeAlias = Literal[
    "SessionStart",
    "SubagentStart",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "PreCompact",
    "PostCompact",
    "UserPromptSubmit",
    "SubagentStop",
    "Stop",
]
PermissionMode: TypeAlias = Literal[
    "default", "acceptEdits", "plan", "dontAsk", "bypassPermissions"
]
StartSource: TypeAlias = Literal["startup", "resume", "clear", "compact"]
CompactTrigger: TypeAlias = Literal["manual", "auto"]


class BaseInput(StrictModel):
    """Fields present on every Codex command-hook input."""

    session_id: str
    transcript_path: str | None
    cwd: str
    hook_event_name: CodexEventName
    model: str


class SessionStartInput(BaseInput):
    hook_event_name: Literal["SessionStart"]
    permission_mode: PermissionMode
    source: StartSource


class SubagentStartInput(BaseInput):
    hook_event_name: Literal["SubagentStart"]
    permission_mode: PermissionMode
    turn_id: str
    agent_id: str
    agent_type: str


class PreToolUseInput(BaseInput):
    hook_event_name: Literal["PreToolUse"]
    permission_mode: PermissionMode
    turn_id: str
    tool_name: str
    tool_use_id: str
    tool_input: Json


class PermissionRequestInput(BaseInput):
    hook_event_name: Literal["PermissionRequest"]
    permission_mode: PermissionMode
    turn_id: str
    tool_name: str
    tool_input: Json


class PostToolUseInput(BaseInput):
    hook_event_name: Literal["PostToolUse"]
    permission_mode: PermissionMode
    turn_id: str
    tool_name: str
    tool_use_id: str
    tool_input: Json
    tool_response: Json


class PreCompactInput(BaseInput):
    hook_event_name: Literal["PreCompact"]
    turn_id: str
    trigger: CompactTrigger


class PostCompactInput(BaseInput):
    hook_event_name: Literal["PostCompact"]
    turn_id: str
    trigger: CompactTrigger


class UserPromptSubmitInput(BaseInput):
    hook_event_name: Literal["UserPromptSubmit"]
    permission_mode: PermissionMode
    turn_id: str
    prompt: str


class SubagentStopInput(BaseInput):
    hook_event_name: Literal["SubagentStop"]
    permission_mode: PermissionMode
    turn_id: str
    agent_id: str
    agent_type: str
    agent_transcript_path: str | None
    stop_hook_active: bool
    last_assistant_message: str | None


class StopInput(BaseInput):
    hook_event_name: Literal["Stop"]
    permission_mode: PermissionMode
    turn_id: str
    stop_hook_active: bool
    last_assistant_message: str | None


AnyInput: TypeAlias = Annotated[
    SessionStartInput
    | SubagentStartInput
    | PreToolUseInput
    | PermissionRequestInput
    | PostToolUseInput
    | PreCompactInput
    | PostCompactInput
    | UserPromptSubmitInput
    | SubagentStopInput
    | StopInput,
    Field(discriminator="hook_event_name"),
]

INPUT_ADAPTER: TypeAdapter[AnyInput] = TypeAdapter(AnyInput)
EVENT_NAMES: tuple[CodexEventName, ...] = (
    "SessionStart",
    "SubagentStart",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "PreCompact",
    "PostCompact",
    "UserPromptSubmit",
    "SubagentStop",
    "Stop",
)

EVENT_NAME_BY_TYPE: dict[type[BaseInput], CodexEventName] = {
    SessionStartInput: "SessionStart",
    SubagentStartInput: "SubagentStart",
    PreToolUseInput: "PreToolUse",
    PermissionRequestInput: "PermissionRequest",
    PostToolUseInput: "PostToolUse",
    PreCompactInput: "PreCompact",
    PostCompactInput: "PostCompact",
    UserPromptSubmitInput: "UserPromptSubmit",
    SubagentStopInput: "SubagentStop",
    StopInput: "Stop",
}


def parse_input(data: JsonInput) -> AnyInput:
    """Strictly parse one Codex command-hook input payload."""

    return INPUT_ADAPTER.validate_python(parse_json_object(data))
