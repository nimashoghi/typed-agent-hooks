"""Codex command-hook input schemas: tolerant readers, strict declared fields."""

from typing import Literal, TypeAlias, cast

from typed_agent_hooks.core import InputModel, Json, JsonInput, parse_json_object

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
StartSource: TypeAlias = Literal["startup", "resume", "clear", "compact", "fork"]
CompactTrigger: TypeAlias = Literal["manual", "auto"]


class BaseInput(InputModel):
    """Fields present on every Codex command-hook input."""

    session_id: str
    transcript_path: str | None
    cwd: str
    hook_event_name: CodexEventName
    model: str
    # Present on events fired from a subagent's context (observed live on
    # PreToolUse/PostToolUse in collaboration mode); absent on the main thread.
    agent_id: str | None = None
    agent_type: str | None = None


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


AnyInput: TypeAlias = (
    SessionStartInput
    | SubagentStartInput
    | PreToolUseInput
    | PermissionRequestInput
    | PostToolUseInput
    | PreCompactInput
    | PostCompactInput
    | UserPromptSubmitInput
    | SubagentStopInput
    | StopInput
)

INPUT_TYPES: dict[str, type[BaseInput]] = {
    "SessionStart": SessionStartInput,
    "SubagentStart": SubagentStartInput,
    "PreToolUse": PreToolUseInput,
    "PermissionRequest": PermissionRequestInput,
    "PostToolUse": PostToolUseInput,
    "PreCompact": PreCompactInput,
    "PostCompact": PostCompactInput,
    "UserPromptSubmit": UserPromptSubmitInput,
    "SubagentStop": SubagentStopInput,
    "Stop": StopInput,
}
"""Input model by native ``hook_event_name``."""


def parse_input(data: JsonInput) -> AnyInput:
    """Strictly parse one Codex command-hook input payload.

    Only the model that ``hook_event_name`` names is validated, so a hook run
    builds one input schema instead of the schema of every event.
    """

    payload = parse_json_object(data)
    name = payload.get("hook_event_name")
    input_type = INPUT_TYPES.get(name) if isinstance(name, str) else None
    if input_type is None:
        raise ValueError(f"unsupported Codex hook event {name!r}")
    return cast(AnyInput, input_type.model_validate(payload))
