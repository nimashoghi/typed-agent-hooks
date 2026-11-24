"""Shared primitives for strict hook schemas and rendering."""

import json
import math
from collections.abc import Mapping
from typing import Any, Literal, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator
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

Json: TypeAlias = JsonValue
JsonInput: TypeAlias = str | bytes | Mapping[str, object]


class CommonOutput(StrictModel):
    """The output field of every event that a shared result can answer."""

    system_message: str | None = Field(default=None, serialization_alias="systemMessage")


class BlockableOutput(CommonOutput):
    """Output of an event that a shared ``Block`` or ``Stop`` can answer.

    Both hosts read the same four fields on these events.
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


def _finite_float(text: str) -> float:
    # A valid JSON number such as 1e400 overflows to infinity.
    if not math.isfinite(value := float(text)):
        raise ValueError(f"{text} is not a finite number")
    return value


def loads_json(text: str | bytes) -> object:
    """Decode JSON text whose every number is finite.

    Python's decoder accepts NaN and Infinity, which are not JSON, and turns a
    number too large for a float into infinity.

    Raises:
        ValueError: If the text is malformed (json.JSONDecodeError) or holds
            such a number.
    """

    return json.loads(text, parse_constant=_reject_constant, parse_float=_finite_float)


def _snapshot(value: object) -> object:
    """Copy a payload, reading each value once, with dicts for mappings and lists
    for lists and tuples; raise for a float that is not finite.

    Iterative, so that deep nesting raises no RecursionError. The handler gets
    the copy, so a mapping that changes between reads cannot change what was
    checked.
    """

    root: list[object] = [value]
    pending: list[tuple[Any, Any]] = [(root, 0)]
    copies: dict[int, tuple[object, object]] = {}  # the original keeps its id unique
    while pending:
        parent, key = pending.pop()
        item = parent[key]
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError(f"{item} is not a finite number")
        if not isinstance(item, Mapping | list | tuple):
            continue
        if (known := copies.get(id(item))) is not None:
            parent[key] = known[1]
            continue
        copy: Any = dict(item) if isinstance(item, Mapping) else list(item)
        copies[id(item)] = (item, copy)
        parent[key] = copy
        pending.extend(
            (copy, index) for index in (copy if isinstance(copy, dict) else range(len(copy)))
        )
    return root[0]


def parse_json_object(data: JsonInput) -> dict[str, object]:
    """Parse hook input and require a JSON object.

    Args:
        data: JSON text/bytes or an existing mapping.

    Returns:
        A mutable dictionary suitable for Pydantic validation.

    Raises:
        TypeError: If the decoded value is not a JSON object.
        ValueError: If JSON text is malformed (json.JSONDecodeError), or the
            payload holds a number that is not finite.
    """

    decoded = loads_json(data) if isinstance(data, (str, bytes)) else _snapshot(data)
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
