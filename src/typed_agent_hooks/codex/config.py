"""Typed Codex ``hooks.json`` command-hook configuration."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from typed_agent_hooks.core import StrictModel

from .events import EVENT_NAMES, CodexEventName

PositiveSeconds = Annotated[int, Field(gt=0)]
MATCHER_EVENTS: frozenset[CodexEventName] = frozenset(
    {
        "PermissionRequest",
        "PostToolUse",
        "PostCompact",
        "PreCompact",
        "PreToolUse",
        "SessionStart",
        "SubagentStart",
        "SubagentStop",
    }
)


class CommandHook(StrictModel):
    """Codex command hook handler."""

    type: Literal["command"] = "command"
    command: str = Field(min_length=1)
    timeout: PositiveSeconds | None = None
    status_message: str | None = Field(
        default=None, validation_alias="statusMessage", serialization_alias="statusMessage"
    )
    command_windows: str | None = Field(
        default=None, validation_alias="commandWindows", serialization_alias="commandWindows"
    )


class HookGroup(StrictModel):
    """Matcher plus one or more Codex command handlers."""

    matcher: str | None = None
    hooks: list[CommandHook] = Field(min_length=1)


class HooksFile(StrictModel):
    """Complete Codex ``hooks.json`` document."""

    hooks: dict[CodexEventName, list[HookGroup]] = Field(min_length=1)

    @model_validator(mode="after")
    def _matchers_are_supported(self) -> HooksFile:
        for event_name, groups in self.hooks.items():
            if event_name in MATCHER_EVENTS:
                continue
            if any(group.matcher is not None for group in groups):
                raise ValueError(f"Codex event {event_name} ignores matchers")
        return self


def build_hooks(
    command: CommandHook,
    *,
    events: tuple[CodexEventName, ...] = EVENT_NAMES,
    matchers: dict[CodexEventName, str] | None = None,
) -> HooksFile:
    """Build a Codex hooks file using one command handler."""

    matcher_by_event = matchers or {}
    hooks = {
        event: [HookGroup(matcher=matcher_by_event.get(event), hooks=[command])] for event in events
    }
    return HooksFile(hooks=hooks)
