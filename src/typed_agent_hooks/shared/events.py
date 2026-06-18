"""Provider-independent semantic events shared by Codex and Claude Code."""

from typing import Annotated, Literal, TypeAlias

from pydantic import Field, TypeAdapter

from typed_agent_hooks.core import Json, Provider, StrictModel

SharedEventName: TypeAlias = Literal[
    "SessionStarted",
    "PromptSubmitted",
    "ToolCallProposed",
    "PermissionRequested",
    "ToolCallCompleted",
    "CompactionStarting",
    "CompactionFinished",
    "SubagentStarted",
    "SubagentStopped",
    "TurnStopped",
]
PermissionMode: TypeAlias = Literal[
    "default", "acceptEdits", "plan", "dontAsk", "bypassPermissions", "auto"
]


class EventContext(StrictModel):
    """Provider provenance and session metadata for a shared event."""

    provider: Provider
    source_event: str
    session_id: str
    transcript_path: str | None
    cwd: str
    model: str | None = None
    permission_mode: PermissionMode | None = None


class BaseEvent(StrictModel):
    """Common provenance shared by every semantic event."""

    context: EventContext


class SessionStarted(BaseEvent):
    event_name: Literal["SessionStarted"] = "SessionStarted"
    source: Literal["startup", "resume", "clear", "compact"]
    session_title: str | None = None


class PromptSubmitted(BaseEvent):
    event_name: Literal["PromptSubmitted"] = "PromptSubmitted"
    turn_id: str | None = None
    prompt: str


class ToolCallProposed(BaseEvent):
    event_name: Literal["ToolCallProposed"] = "ToolCallProposed"
    turn_id: str | None = None
    tool_name: str
    tool_input: Json
    tool_use_id: str


class PermissionRequested(BaseEvent):
    event_name: Literal["PermissionRequested"] = "PermissionRequested"
    turn_id: str | None = None
    tool_name: str
    tool_input: Json


class ToolCallCompleted(BaseEvent):
    event_name: Literal["ToolCallCompleted"] = "ToolCallCompleted"
    turn_id: str | None = None
    tool_name: str
    tool_input: Json
    tool_response: Json
    tool_use_id: str
    duration_ms: int | None = Field(default=None, ge=0)


class CompactionStarting(BaseEvent):
    event_name: Literal["CompactionStarting"] = "CompactionStarting"
    turn_id: str | None = None
    trigger: Literal["manual", "auto"]
    instructions: str | None = None


class CompactionFinished(BaseEvent):
    event_name: Literal["CompactionFinished"] = "CompactionFinished"
    turn_id: str | None = None
    trigger: Literal["manual", "auto"]
    summary: str | None = None


class SubagentStarted(BaseEvent):
    event_name: Literal["SubagentStarted"] = "SubagentStarted"
    turn_id: str | None = None
    agent_id: str
    agent_type: str


class SubagentStopped(BaseEvent):
    event_name: Literal["SubagentStopped"] = "SubagentStopped"
    turn_id: str | None = None
    agent_id: str
    agent_type: str
    agent_transcript_path: str | None = None
    stop_hook_active: bool
    last_assistant_message: str | None


class TurnStopped(BaseEvent):
    event_name: Literal["TurnStopped"] = "TurnStopped"
    turn_id: str | None = None
    stop_hook_active: bool
    last_assistant_message: str | None


AnyEvent: TypeAlias = Annotated[
    SessionStarted
    | PromptSubmitted
    | ToolCallProposed
    | PermissionRequested
    | ToolCallCompleted
    | CompactionStarting
    | CompactionFinished
    | SubagentStarted
    | SubagentStopped
    | TurnStopped,
    Field(discriminator="event_name"),
]

EVENT_ADAPTER: TypeAdapter[AnyEvent] = TypeAdapter(AnyEvent)
EVENT_NAMES: tuple[SharedEventName, ...] = (
    "SessionStarted",
    "PromptSubmitted",
    "ToolCallProposed",
    "PermissionRequested",
    "ToolCallCompleted",
    "CompactionStarting",
    "CompactionFinished",
    "SubagentStarted",
    "SubagentStopped",
    "TurnStopped",
)

EVENT_NAME_BY_TYPE: dict[type[BaseEvent], SharedEventName] = {
    SessionStarted: "SessionStarted",
    PromptSubmitted: "PromptSubmitted",
    ToolCallProposed: "ToolCallProposed",
    PermissionRequested: "PermissionRequested",
    ToolCallCompleted: "ToolCallCompleted",
    CompactionStarting: "CompactionStarting",
    CompactionFinished: "CompactionFinished",
    SubagentStarted: "SubagentStarted",
    SubagentStopped: "SubagentStopped",
    TurnStopped: "TurnStopped",
}
