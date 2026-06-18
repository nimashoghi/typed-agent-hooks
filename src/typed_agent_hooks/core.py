"""Shared primitives for strict hook schemas and rendering."""

import json
from collections.abc import Mapping
from enum import Enum
from typing import TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field
from pydantic.types import JsonValue


class StrictModel(BaseModel):
    """Pydantic model with strict validation, frozen fields, and no unknown keys."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        populate_by_name=True,
        frozen=True,
    )


class Provider(str, Enum):
    """Supported hook providers."""

    CODEX = "codex"
    CLAUDE_CODE = "claude_code"


Json: TypeAlias = JsonValue
JsonInput: TypeAlias = str | bytes | Mapping[str, object]


class PlainTextOutput(StrictModel):
    """Raw stdout returned by events that accept unstructured text."""

    text: str


class CommonOutput(StrictModel):
    """Common structured command-hook output fields."""

    continue_: bool | None = Field(
        default=None, validation_alias="continue", serialization_alias="continue"
    )
    stop_reason: str | None = Field(
        default=None, validation_alias="stopReason", serialization_alias="stopReason"
    )
    system_message: str | None = Field(
        default=None, validation_alias="systemMessage", serialization_alias="systemMessage"
    )
    suppress_output: bool | None = Field(
        default=None, validation_alias="suppressOutput", serialization_alias="suppressOutput"
    )


class ClaudeCommonOutput(CommonOutput):
    """Common Claude Code output fields."""

    terminal_sequence: str | None = Field(
        default=None, validation_alias="terminalSequence", serialization_alias="terminalSequence"
    )


def parse_json_object(data: JsonInput) -> dict[str, object]:
    """Parse hook input and require a JSON object.

    Args:
        data: JSON text/bytes or an existing mapping.

    Returns:
        A mutable dictionary suitable for Pydantic validation.

    Raises:
        TypeError: If the decoded value is not a JSON object.
        json.JSONDecodeError: If JSON text is malformed.
    """

    decoded: object = json.loads(data) if isinstance(data, (str, bytes)) else dict(data)
    if not isinstance(decoded, dict):
        raise TypeError("hook payload must be a JSON object")
    return cast(dict[str, object], decoded)


def render_json(model: BaseModel) -> str:
    """Render a Pydantic model as compact provider wire JSON."""

    return json.dumps(
        model.model_dump(by_alias=True, exclude_none=True),
        ensure_ascii=False,
        separators=(",", ":"),
    )
