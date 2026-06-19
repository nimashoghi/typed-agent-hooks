"""Unit tests for the stdlib-only fastmcp wire protocol + correlation key."""

from __future__ import annotations

import socket

import pytest

from typed_agent_hooks.fastmcp import wire


def test_correlation_key_codex_root():
    assert (
        wire.correlation_key("codex", {"session_id": "S", "hook_event_name": "PreToolUse"}) == "S"
    )


def test_correlation_key_codex_subagent_start_uses_agent_id():
    ev = {"session_id": "P", "agent_id": "A", "hook_event_name": "SubagentStart"}
    assert wire.correlation_key("codex", ev) == "A"


def test_correlation_key_codex_subagent_tool_falls_to_parent_session():
    # tool events carry no agent_id -> parent session_id (ambiguous; the shim no-ops)
    assert (
        wire.correlation_key("codex", {"session_id": "P", "hook_event_name": "PreToolUse"}) == "P"
    )


def test_correlation_key_claude_ignores_agent_id():
    assert wire.correlation_key("claude_code", {"session_id": "S", "agent_id": "A"}) == "S"


def test_correlation_key_missing_or_unknown():
    assert wire.correlation_key("codex", {}) is None
    assert wire.correlation_key("claude_code", {"agent_id": "A"}) is None
    assert wire.correlation_key("other", {"session_id": "S"}) is None


def test_frame_roundtrip_over_socketpair():
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        obj = {"payload": {"text": "line1\nline2", "nested": [1, {"x": "}{"}]}, "k": "v"}
        wire.send_frame(a, obj)
        assert wire.recv_frame(b) == obj
        wire.send_frame(a, wire.response_frame(ok=True, stdout="hi"))
        got = wire.recv_frame(b)
        assert got["ok"] is True and got["stdout"] == "hi"
    finally:
        a.close()
        b.close()


def test_recv_frame_truncated_raises():
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        a.sendall(wire.encode_frame({"x": "y"})[:3])  # partial header only
        a.close()
        with pytest.raises((ConnectionError, OSError, ValueError)):
            wire.recv_frame(b)
    finally:
        b.close()


def test_request_response_envelopes():
    req = wire.request_frame(key="K", provider="codex", server_nonce="N", payload={"a": 1})
    assert req["v"] == wire.PROTOCOL_VERSION
    assert (req["key"], req["provider"], req["server_nonce"], req["payload"]) == (
        "K",
        "codex",
        "N",
        {"a": 1},
    )
    resp = wire.response_frame(ok=False, stdout=None, exit_code=0)
    assert resp == {"v": wire.PROTOCOL_VERSION, "ok": False, "stdout": "", "exit": 0}
