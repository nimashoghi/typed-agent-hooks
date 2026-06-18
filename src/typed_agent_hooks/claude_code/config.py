"""Typed Claude Code command-hook settings configuration."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from typed_agent_hooks.core import StrictModel

from .events import EVENT_NAMES, ClaudeEventName

PositiveSeconds = Annotated[int, Field(gt=0)]
MATCHER_EVENTS: frozenset[ClaudeEventName] = frozenset(
    {
        "PreToolUse",
        "PostToolUse",
        "PostToolUseFailure",
        "PermissionRequest",
        "PermissionDenied",
        "SessionStart",
        "Setup",
        "SessionEnd",
        "Notification",
        "SubagentStart",
        "PreCompact",
        "PostCompact",
        "SubagentStop",
        "ConfigChange",
        "FileChanged",
        "StopFailure",
        "InstructionsLoaded",
        "UserPromptExpansion",
        "Elicitation",
        "ElicitationResult",
    }
)


class CommandHook(StrictModel):
    """Claude Code command hook handler."""

    type: Literal["command"] = "command"
    command: str = Field(min_length=1)
    args: list[str] | None = None
    timeout: PositiveSeconds | None = None
    status_message: str | None = Field(
        default=None, validation_alias="statusMessage", serialization_alias="statusMessage"
    )
    async_: bool | None = Field(default=None, validation_alias="async", serialization_alias="async")
    async_rewake: bool | None = Field(
        default=None, validation_alias="asyncRewake", serialization_alias="asyncRewake"
    )
    shell: str | None = None
    condition: str | None = Field(default=None, validation_alias="if", serialization_alias="if")


class HookGroup(StrictModel):
    """Matcher plus one or more Claude Code command handlers."""

    matcher: str | None = None
    hooks: list[CommandHook] = Field(min_length=1)


class SettingsHooks(StrictModel):
    """Claude Code settings fragment containing command hooks."""

    hooks: dict[ClaudeEventName, list[HookGroup]] = Field(min_length=1)

    @model_validator(mode="after")
    def _matchers_are_supported(self) -> "SettingsHooks":
        for event_name, groups in self.hooks.items():
            if event_name in MATCHER_EVENTS:
                continue
            if any(group.matcher is not None for group in groups):
                raise ValueError(f"Claude Code event {event_name} ignores matchers")
        return self


def build_settings_hooks(
    command: CommandHook,
    *,
    events: tuple[ClaudeEventName, ...] = EVENT_NAMES,
    matchers: dict[ClaudeEventName, str] | None = None,
) -> SettingsHooks:
    """Build a Claude Code settings hook fragment using one command handler."""

    matcher_by_event = matchers or {}
    hooks = {
        event: [HookGroup(matcher=matcher_by_event.get(event), hooks=[command])] for event in events
    }
    return SettingsHooks(hooks=hooks)
