"""Windows-semantics degradation: no geteuid/AF_UNIX -> inactive, never crash.

Runs on every platform (unlike the rendezvous/shim/bridge suites, which are
Linux-only). On Linux the tests DELETE ``os.geteuid`` / ``socket.AF_UNIX``
(monkeypatch restores them per test) to simulate native Windows through the
real ``rendezvous.supported()`` mechanism; on real Windows the ``raising=False``
deletions are no-ops and the same assertions hold natively.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import os
import socket
from contextlib import asynccontextmanager

import pytest

from typed_agent_hooks.fastmcp import rendezvous as rz
from typed_agent_hooks.fastmcp import shim


def _simulate_no_posix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(os, "geteuid", raising=False)
    monkeypatch.delattr(socket, "AF_UNIX", raising=False)


@asynccontextmanager
async def _yield(value):
    yield value


def _shim_args() -> argparse.Namespace:
    return argparse.Namespace(
        provider="codex", server_name="ipi", hookset_name=None, registry_root=None
    )


_EVENT = json.dumps({"session_id": "S", "hook_event_name": "PreToolUse"})


def test_supported_false_without_posix_primitives(monkeypatch):
    _simulate_no_posix(monkeypatch)
    assert rz.supported() is False


def test_runtime_base_none_when_unsupported(monkeypatch, tmp_path):
    _simulate_no_posix(monkeypatch)
    assert rz.runtime_base() is None
    explicit = tmp_path / "reg"
    assert rz.runtime_base(explicit=explicit) is None
    assert not explicit.exists()  # the gate fires before any mkdir/chmod


def test_shim_run_is_noop_when_unsupported(monkeypatch, capsys):
    _simulate_no_posix(monkeypatch)
    # _run (un-suppressed) must return cleanly via the base gate, not raise.
    monkeypatch.setattr("sys.stdin", io.StringIO(_EVENT))
    shim._run(_shim_args())
    # run_from_args pins the fail-open contract (exit 0, empty stdout).
    monkeypatch.setattr("sys.stdin", io.StringIO(_EVENT))
    assert shim.run_from_args(_shim_args()) == 0
    assert capsys.readouterr().out == ""


def test_bridge_lifespan_inactive_when_unsupported(monkeypatch):
    fastmcp = pytest.importorskip("fastmcp")  # import BEFORE deleting attributes
    from typed_agent_hooks.fastmcp import bridge as B

    # Delete only geteuid here (enough to flip supported() False): on Linux,
    # removing socket.AF_UNIX would break asyncio's own event-loop self-pipe
    # (socket.socketpair() falls back to AF_INET, unsupported by Linux
    # socketpair(2)) — a simulation artifact real Windows does not have.
    monkeypatch.delattr(os, "geteuid", raising=False)
    sentinel = object()
    server = fastmcp.FastMCP("t", lifespan=lambda s: _yield(sentinel))
    bridge = B.attach(server, object(), provider="codex", server_name="ipi")

    state: dict = {}

    async def body():
        async with server._lifespan(server) as result:
            state["yielded_is_sentinel"] = result is sentinel

    asyncio.run(body())  # goes through the REAL runtime_base gate (no rz patching)
    assert state["yielded_is_sentinel"] is True
    assert bridge._listener is None and bridge._descriptor is None
    assert bridge._anchor_dir is None


def test_bridge_lifespan_survives_startup_error(monkeypatch, caplog):
    fastmcp = pytest.importorskip("fastmcp")
    from typed_agent_hooks.fastmcp import bridge as B

    def _boom(explicit=None):
        raise RuntimeError("registry exploded")

    monkeypatch.setattr(rz, "runtime_base", _boom)
    sentinel = object()
    server = fastmcp.FastMCP("t", lifespan=lambda s: _yield(sentinel))
    bridge = B.attach(server, object(), provider="codex", server_name="ipi")

    state: dict = {}

    async def body():
        async with server._lifespan(server) as result:
            state["yielded_is_sentinel"] = result is sentinel

    with caplog.at_level(logging.WARNING, logger="typed_agent_hooks.fastmcp.bridge"):
        asyncio.run(body())
    assert state["yielded_is_sentinel"] is True
    assert bridge._listener is None
    assert "bridge startup failed" in caplog.text


def test_bridge_lifespan_survives_teardown_error(monkeypatch, caplog):
    fastmcp = pytest.importorskip("fastmcp")
    from typed_agent_hooks.fastmcp import bridge as B

    monkeypatch.setattr(rz, "runtime_base", lambda explicit=None: None)  # inactive
    monkeypatch.setattr(B.HookBridge, "_teardown", _boom_teardown)
    server = fastmcp.FastMCP("t", lifespan=lambda s: _yield(None))
    B.attach(server, object(), provider="codex", server_name="ipi")

    async def body():
        async with server._lifespan(server):
            pass

    with caplog.at_level(logging.WARNING, logger="typed_agent_hooks.fastmcp.bridge"):
        asyncio.run(body())  # must not raise out of the lifespan
    assert "teardown failed" in caplog.text


async def _boom_teardown(self):
    raise RuntimeError("teardown exploded")
