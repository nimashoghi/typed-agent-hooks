"""Shared primitives for strict hook schemas and rendering."""

import json
from collections.abc import Mapping
from typing import Literal, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field
from pydantic.types import JsonValue


class StrictModel(BaseModel):
    """Pydantic model with strict validation, frozen fields, and no unknown keys."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        populate_by_name=True,
        frozen=True,
        # A hook run builds only the schemas that it uses, not all at import.
        defer_build=True,
    )


class InputModel(BaseModel):
    """Tolerant-reader wire input: strict declared fields, unknown keys ignored.

    Hosts add payload fields at will, and an unknown key must never turn
    into a dropped event: Claude Code's `prompt_id` addition silently killed
    every tool event while schemas forbade extras. Declared fields stay
    strictly typed, so drift on a known field still fails loudly. Outputs
    remain `StrictModel`: we author those, and they must be exact.
    """

    model_config = ConfigDict(
        extra="ignore",
        strict=True,
        populate_by_name=True,
        frozen=True,
        # A hook run builds only the schemas that it uses, not all at import.
        defer_build=True,
    )


Host: TypeAlias = Literal["codex", "claude"]
"""A hook host, named as the first argument of a hook command."""
HOSTS: tuple[Host, ...] = ("codex", "claude")

Json: TypeAlias = JsonValue
JsonInput: TypeAlias = str | bytes | Mapping[str, object]


class CommonOutput(StrictModel):
    """Structured command-hook output fields common to both hosts."""

    continue_: bool | None = Field(
        default=None, validation_alias="continue", serialization_alias="continue"
    )
    stop_reason: str | None = Field(
        default=None, validation_alias="stopReason", serialization_alias="stopReason"
    )
    system_message: str | None = Field(
        default=None, validation_alias="systemMessage", serialization_alias="systemMessage"
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
    """Render a Pydantic model as compact host wire JSON."""

    return json.dumps(
        model.model_dump(by_alias=True, exclude_none=True),
        ensure_ascii=False,
        separators=(",", ":"),
    )
