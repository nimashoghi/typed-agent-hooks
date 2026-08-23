"""Tests for the provider-facing FastMCP forwarding CLI."""

from __future__ import annotations

import io
import json
import sys

import pytest

from typed_agent_hooks.fastmcp import shim


def test_forward_cli_does_not_wrap_long_provider_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "context " * 200,
            }
        },
        separators=(",", ":"),
    )
    monkeypatch.setattr(shim, "_run", lambda *args, **kwargs: output)
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"session_id":"session"}'))

    assert shim.app(["-", "--provider", "codex"]) == 0

    assert capsys.readouterr().out == f"{output}\n"
