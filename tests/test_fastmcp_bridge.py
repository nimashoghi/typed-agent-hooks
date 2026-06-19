"""Integration tests for the server-side FastMCP bridge (requires the [fastmcp] extra).

No async pytest plugin is configured, so async paths are driven via ``asyncio.run``.
The tests act as the "shim" by speaking the wire protocol over the bridge's socket.
A short temp base (not pytest's long ``tmp_path``) keeps unix-socket paths under the
~108-byte AF_UNIX limit.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

pytest.importorskip("fastmcp")

from fastmcp import FastMCP  # noqa: E402

from typed_agent_hooks import codex  # noqa: E402
from typed_agent_hooks.core import PlainTextOutput  # noqa: E402
from typed_agent_hooks.fastmcp import bridge as B  # noqa: E402
from typed_agent_hooks.fastmcp import rendezvous as rz  # noqa: E402
from typed_agent_hooks.fastmcp import wire  # noqa: E402

# A valid Codex SessionStart payload (mirrors tests/fixtures/codex_inputs.json).
SESSION_START = {
    "session_id": "s",
    "transcript_path": None,
    "cwd": "/repo",
    "hook_event_name": "SessionStart",
    "model": "gpt-5",
    "permission_mode": "default",
    "source": "startup",
}
_ANCHOR = (100, 200)


@pytest.fixture
def short_base() -> Iterator[Path]:
    d = Path(tempfile.mkdtemp(prefix="thb"))
    os.chmod(d, 0o700)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _patch_registry(monkeypatch, base: Path):
    monkeypatch.setattr(rz, "runtime_base", lambda explicit=None: base)
    monkeypatch.setattr(rz, "find_harness_anchor", lambda *a, **k: _ANCHOR)
    # Behave like Codex (no eager env bind) so bound_key starts None.
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)


@asynccontextmanager
async def _yield(value):
    yield value


def _app_returning(text, *, record=None):
    app = codex.HookApp()

    @app.on(codex.events.SessionStartInput)
    def _handler(ev):  # sync handler (the registry rejects async)
        if record is not None:
            record.append(ev.session_id)
        return PlainTextOutput(text=text)

    return app


async def _client_forward(desc: dict, payload: dict, *, key: str, nonce: str | None = None):
    reader, writer = await asyncio.open_unix_connection(desc["socket_path"])
    try:
        req = wire.request_frame(
            key=key,
            provider="codex",
            server_nonce=nonce if nonce is not None else desc["server_nonce"],
            payload=payload,
        )
        writer.write(wire.encode_frame(req))
        await writer.drain()
        header = await reader.readexactly(wire.header_size())
        length = wire.unpack_length(header)
        return wire.decode_body(length, await reader.readexactly(length))
    finally:
        writer.close()


def test_lifespan_wrap_yields_through_serves_and_cleans_up(short_base, monkeypatch):
    _patch_registry(monkeypatch, short_base)
    sentinel = object()

    server = FastMCP("t", lifespan=lambda s: _yield(sentinel))
    original = server._lifespan
    B.attach(server, _app_returning("HELLO_FROM_HANDLER"), provider="codex", server_name="ipi")
    assert server._lifespan is not original  # wrapped

    state: dict = {}

    async def body():
        async with server._lifespan(server) as result:
            state["yielded_is_sentinel"] = result is sentinel
            adir = short_base / "100-200"
            descs = rz.list_descriptors(adir)
            assert len(descs) == 1 and descs[0]["server_name"] == "ipi"
            assert Path(descs[0]["socket_path"]).exists()
            state["adir"] = adir
            state["sock"] = descs[0]["socket_path"]
            resp = await _client_forward(descs[0], SESSION_START, key="s")
            state["out"] = resp["stdout"]
            state["ok"] = resp["ok"]

    asyncio.run(body())
    assert state["yielded_is_sentinel"] is True  # G4: original lifespan result preserved
    assert state["ok"] is True and state["out"] == "HELLO_FROM_HANDLER"  # dispatched via HookApp
    # G4: teardown cleaned descriptor + socket
    assert rz.list_descriptors(state["adir"]) == []
    assert not Path(state["sock"]).exists()


def test_threadid_bind_and_drain(short_base, monkeypatch):
    _patch_registry(monkeypatch, short_base)
    ran: list[str] = []

    server = FastMCP("t", lifespan=lambda s: _yield(None))
    bridge = B.attach(server, _app_returning("x", record=ran), provider="codex", server_name="ipi")

    async def body():
        async with server._lifespan(server):
            adir = short_base / "100-200"
            assert rz.list_descriptors(adir)[0]["bound_key"] is None  # codex: unbound at start
            frame = wire.encode_frame(
                wire.request_frame(
                    key="T", provider="codex", server_nonce="", payload=SESSION_START
                )
            )
            assert rz.enqueue_pending(adir, "T", frame)
            bridge._maybe_bind("T")
            d2 = rz.list_descriptors(adir)[0]
            assert d2["bound_key"] == "T" and d2["generation"] >= 2  # rebound atomically
            await asyncio.sleep(0.2)  # let the drained dispatch run

    asyncio.run(body())
    assert ran == ["s"]  # the buffered SessionStart was dispatched on bind


def test_rejects_wrong_nonce(short_base, monkeypatch):
    _patch_registry(monkeypatch, short_base)
    server = FastMCP("t", lifespan=lambda s: _yield(None))
    B.attach(server, _app_returning("SHOULD_NOT_APPEAR"), provider="codex", server_name="ipi")

    state: dict = {}

    async def body():
        async with server._lifespan(server):
            desc = rz.list_descriptors(short_base / "100-200")[0]
            state["resp"] = await _client_forward(desc, SESSION_START, key="s", nonce="WRONG")

    asyncio.run(body())
    assert state["resp"]["ok"] is False and state["resp"]["stdout"] == ""


def test_inactive_when_no_harness_anchor(short_base, monkeypatch):
    monkeypatch.setattr(rz, "runtime_base", lambda explicit=None: short_base)
    monkeypatch.setattr(rz, "find_harness_anchor", lambda *a, **k: None)  # e.g. HTTP / not a child
    sentinel = object()
    server = FastMCP("t", lifespan=lambda s: _yield(sentinel))
    B.attach(server, _app_returning("x"), provider="codex", server_name="ipi")

    state: dict = {}

    async def body():
        async with server._lifespan(server) as result:
            state["ok"] = result is sentinel
            state["no_anchor_dir"] = not (short_base / "100-200").exists()

    asyncio.run(body())
    assert state["ok"] is True and state["no_anchor_dir"] is True
