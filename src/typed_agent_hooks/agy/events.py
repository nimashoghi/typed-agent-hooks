"""Antigravity CLI (`agy`) command-hook input schemas: tolerant readers, strict declared fields.

agy writes camelCase keys. Each model reads a key by its alias and exposes it
under a snake_case name. agy sends no permission mode, turn ID or tool output.
"""

from typing import Literal, TypeAlias, cast

from pydantic import Field

from typed_agent_hooks.core import InputModel, Json, JsonInput, parse_json_object


class BaseInput(InputModel):
    """Fields present on every agy hook input."""

    conversation_id: str = Field(alias="conversationId")
    transcript_path: str = Field(alias="transcriptPath")
    # The agent's working directory, not the hook process's: agy runs a hook
    # in the folder that holds its hooks.json.
    cwd: str
    hook_event_name: str = Field(alias="hookEventName")
    model: str = Field(alias="modelName")


class SessionStartInput(BaseInput):
    """A new conversation. agy does not fire SessionStart when it resumes one."""

    hook_event_name: Literal["SessionStart"] = Field(alias="hookEventName")


class PreInvocationInput(BaseInput):
    """Before every model call, not only before the first call of a user turn."""

    hook_event_name: Literal["PreInvocation"] = Field(alias="hookEventName")
    # 0 at the first model call of a run, which a user prompt, a background
    # message or a continuing Stop hook starts.
    invocation_num: int = Field(alias="invocationNum", ge=0)
    # The number of transcript steps before this model call.
    initial_num_steps: int = Field(alias="initialNumSteps", ge=0)
    # The text of the most recent user prompt. A run that a background message
    # or a Stop hook started repeats the prompt before it.
    last_user_input: str | None = Field(default=None, alias="lastUserInput")


class ToolCall(InputModel):
    id: str
    name: str
    args: dict[str, Json]


class PreToolUseInput(BaseInput):
    hook_event_name: Literal["PreToolUse"] = Field(alias="hookEventName")
    tool_call: ToolCall = Field(alias="toolCall")


class PostToolUseInput(BaseInput):
    """After a tool call. agy sends the error of a failed call, and never the output."""

    hook_event_name: Literal["PostToolUse"] = Field(alias="hookEventName")
    tool_call: ToolCall = Field(alias="toolCall")
    error: str = ""


class StopInput(BaseInput):
    hook_event_name: Literal["Stop"] = Field(alias="hookEventName")
    # How many times a Stop hook has kept this turn going. agy 1.5.16 leaves
    # continuationActive false after a Stop hook continued the turn.
    execution_num: int = Field(alias="executionNum", ge=0)
    continuation_active: bool = Field(default=False, alias="continuationActive")
    # Why the run ended: shared.adapters.AGY_FINISHED when the model finished,
    # AGY_UNFINISHED for a cancel, an error, a limit or a hook that ended it.
    termination_reason: str = Field(alias="terminationReason")


AnyInput: TypeAlias = (
    SessionStartInput | PreInvocationInput | PreToolUseInput | PostToolUseInput | StopInput
)

INPUT_TYPES: dict[str, type[BaseInput]] = {
    "SessionStart": SessionStartInput,
    "PreInvocation": PreInvocationInput,
    "PreToolUse": PreToolUseInput,
    "PostToolUse": PostToolUseInput,
    "Stop": StopInput,
}
"""Input model by native ``hookEventName``."""


def parse_input(data: JsonInput) -> AnyInput:
    """Strictly parse one agy command-hook input payload.

    Only the model that ``hookEventName`` names is validated. ``PostInvocation``
    has no shared equivalent and is not modeled.
    """

    payload = parse_json_object(data)
    name = payload.get("hookEventName")
    input_type = INPUT_TYPES.get(name) if isinstance(name, str) else None
    if input_type is None:
        raise ValueError(f"unsupported agy hook event {name!r}")
    return cast(AnyInput, input_type.model_validate(payload))
