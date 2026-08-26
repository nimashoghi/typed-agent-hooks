"""Code-first provider registration metadata for shared semantic hooks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from typed_agent_hooks.core import StrictModel

from .events import SharedEventName

if TYPE_CHECKING:
    from typed_agent_hooks import claude_code, codex

PositiveSeconds = Annotated[int, Field(gt=0)]


class CodexOptions(StrictModel):
    """Codex-only configuration for one shared semantic handler."""

    matcher: str | None = None
    timeout: PositiveSeconds | None = None
    status_message: str | None = None
    command_windows: str | None = None


class ClaudeCodeOptions(StrictModel):
    """Claude Code-only configuration for one shared semantic handler."""

    matcher: str | None = None
    timeout: PositiveSeconds | None = None
    status_message: str | None = None
    condition: str | None = None
    async_: bool | None = None
    async_rewake: bool | None = None
    shell: str | None = None


SHARED_TO_CODEX: dict[SharedEventName, codex.events.CodexEventName] = {
    "SessionStarted": "SessionStart",
    "PromptSubmitted": "UserPromptSubmit",
    "ToolCallProposed": "PreToolUse",
    "PermissionRequested": "PermissionRequest",
    "ToolCallCompleted": "PostToolUse",
    "CompactionStarting": "PreCompact",
    "CompactionFinished": "PostCompact",
    "SubagentStarted": "SubagentStart",
    "SubagentStopped": "SubagentStop",
    "TurnStopped": "Stop",
}
SHARED_TO_CLAUDE_CODE: dict[SharedEventName, claude_code.events.ClaudeEventName] = {
    "SessionStarted": "SessionStart",
    "PromptSubmitted": "UserPromptSubmit",
    "ToolCallProposed": "PreToolUse",
    "PermissionRequested": "PermissionRequest",
    "ToolCallCompleted": "PostToolUse",
    "ToolCallFailed": "PostToolUseFailure",
    "CompactionStarting": "PreCompact",
    "CompactionFinished": "PostCompact",
    "SubagentStarted": "SubagentStart",
    "SubagentStopped": "SubagentStop",
    "TurnStopped": "Stop",
}
