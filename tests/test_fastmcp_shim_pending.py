"""Portable regression coverage for events waiting on a FastMCP bridge."""

from __future__ import annotations

from pathlib import Path

import pytest

from typed_agent_hooks.fastmcp import rendezvous as rz
from typed_agent_hooks.fastmcp import shim, wire

pytestmark = pytest.mark.skipif(
    not rz.supported(), reason="the pending queue requires POSIX ownership and AF_UNIX"
)

_ANCHOR = (100, 200)


def _patch_registry(monkeypatch: pytest.MonkeyPatch, base: Path) -> Path:
    monkeypatch.setattr(shim.rz, "runtime_base", lambda explicit=None: base)
    monkeypatch.setattr(shim.rz, "find_harness_anchor", lambda *args, **kwargs: _ANCHOR)
    monkeypatch.setattr(shim.rz, "sweep_base", lambda *args, **kwargs: None)
    return rz.anchor_dir(base, _ANCHOR)


def _run(event: dict[str, object], *, provider: str = "codex") -> None:
    assert (
        shim._run(
            event,
            provider=provider,
            server_name="ipi",
            registry_root=None,
            startup_wait=0,
            response_timeout=2,
        )
        is None
    )


def _claim_request(anchor: Path, key: str) -> dict[str, object]:
    frames = rz.claim_pending(anchor, key, "test")
    assert len(frames) == 1
    frame = frames[0]
    header_size = wire.header_size()
    length = wire.unpack_length(frame[:header_size])
    request = wire.decode_body(length, frame[header_size:])
    assert isinstance(request, dict)
    return request


@pytest.mark.parametrize("provider", ["codex", "claude_code"])
def test_user_prompt_without_descriptor_waits_for_bridge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    base = tmp_path / "registry"
    base.mkdir(mode=0o700)
    anchor = _patch_registry(monkeypatch, base)
    event: dict[str, object] = {
        "session_id": "root-thread",
        "hook_event_name": "UserPromptSubmit",
        "prompt": "first prompt",
    }

    _run(event, provider=provider)

    request = _claim_request(anchor, "root-thread")
    assert request["key"] == "root-thread"
    assert request["provider"] == provider
    assert request["payload"] == event


def test_user_prompt_with_ambiguous_descriptors_waits_for_exact_bridge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "registry"
    base.mkdir(mode=0o700)
    anchor = _patch_registry(monkeypatch, base)
    monkeypatch.setattr(
        shim,
        "_live_descriptors",
        lambda *args, **kwargs: [{"bound_key": None}, {"bound_key": "other-thread"}],
    )
    event: dict[str, object] = {
        "session_id": "root-thread",
        "hook_event_name": "UserPromptSubmit",
        "prompt": "first prompt",
    }

    _run(event)

    assert _claim_request(anchor, "root-thread")["payload"] == event


def test_unroutable_tool_event_is_not_buffered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "registry"
    base.mkdir(mode=0o700)
    anchor = _patch_registry(monkeypatch, base)

    _run({"session_id": "root-thread", "hook_event_name": "PreToolUse"})

    assert rz.claim_pending(anchor, "root-thread", "test") == []
