"""Explicit shared-event to provider-event mapping."""

from collections.abc import Mapping

from typed_agent_hooks import claude_code, codex
from typed_agent_hooks.shared.events import SharedEventName

SHARED_TO_CODEX: Mapping[SharedEventName, codex.events.CodexEventName] = {
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
SHARED_TO_CLAUDE_CODE: Mapping[SharedEventName, claude_code.events.ClaudeEventName] = {
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
