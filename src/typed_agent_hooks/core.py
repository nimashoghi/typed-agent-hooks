"""Shared primitives for strict hook schemas and rendering."""

import json
import math
from collections.abc import Mapping
from typing import Annotated, Literal, TypeAlias, cast

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator
from pydantic.types import JsonValue


class StrictModel(BaseModel):
    """Pydantic model with strict validation, frozen fields, and no unknown keys."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
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
        frozen=True,
        # A hook run builds only the schemas that it uses, not all at import.
        defer_build=True,
    )


Host: TypeAlias = Literal["codex", "claude", "agy"]
"""A hook host, named as the first argument of a hook command. ``agy`` is the Antigravity CLI."""
HOSTS: tuple[Host, ...] = ("codex", "claude", "agy")


def _finite(value: JsonValue) -> JsonValue:
    # Iterative: JsonValue has already built the containers, and nesting can be deep.
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError(f"{item} is not a finite number")
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return value


Json: TypeAlias = Annotated[JsonValue, AfterValidator(_finite)]
"""A JSON value whose numbers are finite, as JSON's are; in Python and JSON mode
alike, pydantic's JsonValue alone accepts NaN and infinity."""
JsonInput: TypeAlias = str | bytes | Mapping[str, object]


class CommonOutput(StrictModel):
    """The output field of every Codex and Claude Code event that a shared
    result can answer."""

    system_message: str | None = Field(default=None, serialization_alias="systemMessage")


class BlockableOutput(CommonOutput):
    """Output of an event that a shared ``Block`` or ``Stop`` can answer.

    Codex and Claude Code read the same four fields on these events.
    """

    continue_: bool | None = Field(default=None, serialization_alias="continue")
    stop_reason: str | None = Field(default=None, serialization_alias="stopReason")
    decision: Literal["block"] | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _block_requires_reason(self) -> "BlockableOutput":
        if self.decision == "block" and not self.reason:
            raise ValueError("reason is required when decision='block'")
        return self


def _reject_constant(name: str) -> object:
    raise ValueError(f"{name} is not JSON")


def loads_json(text: str | bytes) -> object:
    """Decode JSON text, refusing NaN and Infinity, which Python's decoder
    accepts but which are not JSON.

    Raises:
        ValueError: If the text is malformed (json.JSONDecodeError) or holds
            NaN or Infinity.
    """

    return json.loads(text, parse_constant=_reject_constant)


def parse_json_object(data: JsonInput) -> dict[str, object]:
    """Parse hook input and require a JSON object.

    Args:
        data: JSON text/bytes or an existing mapping.

    Returns:
        A mutable dictionary suitable for Pydantic validation.

    Raises:
        TypeError: If the decoded value is not a JSON object.
        ValueError: If JSON text is malformed (json.JSONDecodeError) or holds
            NaN or Infinity, which are not JSON.
    """

    decoded: object = loads_json(data) if isinstance(data, (str, bytes)) else dict(data)
    if not isinstance(decoded, dict):
        raise TypeError("hook payload must be a JSON object")
    return cast(dict[str, object], decoded)


def render_json(model: BaseModel) -> str:
    """Render a Pydantic model as compact host wire JSON."""

    # NaN and Infinity are not JSON; json.dumps would write them anyway.
    rendered = json.dumps(
        model.model_dump(by_alias=True, exclude_none=True),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    # The hosts read UTF-8; a lone surrogate (from a file name, say) has none.
    rendered.encode()
    return rendered
