"""Claude Code command-hook input schemas: tolerant readers, strict declared fields."""

from typing import Literal, TypeAlias, cast

from pydantic import Field

from typed_agent_hooks.core import InputModel, Json, JsonInput, parse_json_object

PermissionMode: TypeAlias = Literal[
    "default", "plan", "acceptEdits", "auto", "dontAsk", "bypassPermissions"
]
StartSource: TypeAlias = Literal["startup", "resume", "clear", "compact", "fork"]
CompactTrigger: TypeAlias = Literal["manual", "auto"]


class BaseInput(InputModel):
    """Common Claude Code command-hook input fields that the shared events read."""

    session_id: str
    transcript_path: str
    cwd: str
    hook_event_name: str
    prompt_id: str | None = None
    scratchpad_dir: str | None = None
    permission_mode: PermissionMode | None = None
    agent_id: str | None = None
    agent_type: str | None = None


class SessionStartInput(BaseInput):
    hook_event_name: Literal["SessionStart"]
    source: StartSource
    model: str | None = None
    session_title: str | None = None


class UserPromptSubmitInput(BaseInput):
    hook_event_name: Literal["UserPromptSubmit"]
    prompt: str


class PreToolUseInput(BaseInput):
    hook_event_name: Literal["PreToolUse"]
    tool_name: str
    tool_input: Json
    tool_use_id: str


class PermissionRequestInput(BaseInput):
    hook_event_name: Literal["PermissionRequest"]
    tool_name: str
    tool_input: Json


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


class StopInput(BaseInput):
    hook_event_name: Literal["Stop"]
    stop_hook_active: bool
    last_assistant_message: str | None


class PreCompactInput(BaseInput):
    hook_event_name: Literal["PreCompact"]
    trigger: CompactTrigger
    # Null for automatic compaction and for /compact with no instructions.
    custom_instructions: str | None


class PostCompactInput(BaseInput):
    hook_event_name: Literal["PostCompact"]
    trigger: CompactTrigger
    compact_summary: str


AnyInput: TypeAlias = (
    SessionStartInput
    | UserPromptSubmitInput
    | PreToolUseInput
    | PermissionRequestInput
    | PostToolUseInput
    | PostToolUseFailureInput
    | SubagentStartInput
    | SubagentStopInput
    | StopInput
    | PreCompactInput
    | PostCompactInput
)

INPUT_TYPES: dict[str, type[BaseInput]] = {
    "SessionStart": SessionStartInput,
    "UserPromptSubmit": UserPromptSubmitInput,
    "PreToolUse": PreToolUseInput,
    "PermissionRequest": PermissionRequestInput,
    "PostToolUse": PostToolUseInput,
    "PostToolUseFailure": PostToolUseFailureInput,
    "SubagentStart": SubagentStartInput,
    "SubagentStop": SubagentStopInput,
    "Stop": StopInput,
    "PreCompact": PreCompactInput,
    "PostCompact": PostCompactInput,
}
"""Input model by native ``hook_event_name``."""


def parse_input(data: JsonInput) -> AnyInput:
    """Strictly parse one Claude Code command-hook input payload.

    Only the model that ``hook_event_name`` names is validated, so a hook run
    builds one input schema instead of the schema of every event.
    """

    payload = parse_json_object(data)
    name = payload.get("hook_event_name")
    input_type = INPUT_TYPES.get(name) if isinstance(name, str) else None
    if input_type is None:
        raise ValueError(f"unsupported Claude Code hook event {name!r}")
    return cast(AnyInput, input_type.model_validate(payload))
