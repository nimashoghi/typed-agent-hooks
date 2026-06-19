"""Tests for the stdlib-only forward shim (resolution ladder + fail-open)."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import socket
import struct
import threading

from typed_agent_hooks.fastmcp import rendezvous as rz
from typed_agent_hooks.fastmcp import shim, wire


class FakeServer:
    """A minimal unix-socket server: accept -> recv one frame -> send `response`."""

    def __init__(self, sock_path: str, response: dict | None):
        self.sock_path = sock_path
        self.response = response
        self.received: list[dict] = []
        self._stop = False
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(sock_path)
        self._srv.listen(8)
        self._srv.settimeout(0.1)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop:
            try:
                conn, _ = self._srv.accept()
            except (TimeoutError, OSError):
                continue
            try:
                self.received.append(wire.recv_frame(conn))
                if self.response is not None:
                    wire.send_frame(conn, self.response)
            except Exception:
                pass
            finally:
                conn.close()

    def close(self) -> None:
        self._stop = True
        with contextlib.suppress(OSError):
            self._srv.close()
        with contextlib.suppress(OSError):
            os.unlink(self.sock_path)


def _anchor(tmp_path):
    a = tmp_path / "100-200"
    a.mkdir(mode=0o700)
    return a


def _make_descriptor(anchor, *, nonce, bound_key, generation=1):
    st = rz.read_proc_stat(os.getpid())
    assert st is not None
    desc = rz.Descriptor(
        server_nonce=nonce,
        socket_path=str(rz.socket_path(anchor, nonce)),
        bound_key=bound_key,
        pid=os.getpid(),
        starttime=st[1],
        generation=generation,
        cwd="/x",
        provider="codex",
        server_name="ipi",
    )
    rz.write_descriptor(anchor, desc)
    return desc.socket_path


# ---- pure resolution logic ----


def test_resolve_exact_prefers_newest():
    d1 = {"bound_key": "K", "generation": 1, "starttime": 10}
    d2 = {"bound_key": "K", "generation": 2, "starttime": 20}
    d3 = {"bound_key": "OTHER", "generation": 9}
    assert shim._resolve([d1, d2, d3], "K") is d2


def test_resolve_single_server():
    d = {"bound_key": None}
    assert shim._resolve([d], "K") is d


def test_resolve_ambiguous_returns_none():
    assert shim._resolve([{"bound_key": None}, {"bound_key": "X"}], "K") is None


def test_is_own_identity_event():
    own = {"agent_id": "A", "hook_event_name": "SubagentStart"}
    assert shim._is_own_identity_event("codex", own) is True
    assert (
        shim._is_own_identity_event("codex", {"agent_id": "A", "hook_event_name": "PreToolUse"})
        is False
    )
    assert shim._is_own_identity_event("codex", {"hook_event_name": "SubagentStart"}) is False
    assert shim._is_own_identity_event("claude_code", own) is False


# ---- _forward against a real fake socket ----


def test_forward_success(tmp_path):
    anchor = _anchor(tmp_path)
    sp = _make_descriptor(anchor, nonce="abc", bound_key="K")
    srv = FakeServer(sp, wire.response_frame(ok=True, stdout="HELLO"))
    try:
        desc = rz.list_descriptors(anchor)[0]
        res = shim._forward(desc, key="K", provider="codex", payload={"a": 1})
        assert res.connected is True and res.out == "HELLO"
        assert srv.received[0]["key"] == "K"
        assert srv.received[0]["server_nonce"] == "abc"
        assert srv.received[0]["payload"] == {"a": 1}
    finally:
        srv.close()


def test_forward_missing_server_prunes(tmp_path, monkeypatch):
    monkeypatch.setattr(shim, "_CONNECT_RETRIES", 1)
    monkeypatch.setattr(shim, "_CONNECT_RETRY_SLEEP", 0)
    anchor = _anchor(tmp_path)
    _make_descriptor(anchor, nonce="abc", bound_key="K")  # descriptor, but nobody listening
    desc = rz.list_descriptors(anchor)[0]
    res = shim._forward(desc, key="K", provider="codex", payload={})
    assert res.connected is False
    assert rz.list_descriptors(anchor) == []  # stale descriptor pruned


def test_forward_post_connect_close_is_noop(tmp_path):
    anchor = _anchor(tmp_path)
    sp = _make_descriptor(anchor, nonce="abc", bound_key="K")
    srv = FakeServer(sp, response=None)  # accepts, reads, closes without replying
    try:
        desc = rz.list_descriptors(anchor)[0]
        res = shim._forward(desc, key="K", provider="codex", payload={})
        assert res.connected is True and res.out is None
    finally:
        srv.close()


# ---- run_from_args end to end (monkeypatched anchor + base) ----


def _patch_registry(monkeypatch, base):
    monkeypatch.setattr(shim.rz, "find_harness_anchor", lambda *a, **k: (100, 200))
    monkeypatch.setattr(shim.rz, "runtime_base", lambda explicit=None: base)
    monkeypatch.setattr(shim.rz, "sweep_base", lambda *a, **k: None)


def _args():
    return argparse.Namespace(
        provider="codex", server_name="ipi", hookset_name=None, registry_root=None
    )


def _run(monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    rc = shim.run_from_args(_args())
    return rc, out.getvalue()


def test_run_forwards_to_exact_match(tmp_path, monkeypatch):
    base = tmp_path / "base"
    base.mkdir(mode=0o700)
    adir = base / "100-200"
    adir.mkdir(mode=0o700)
    sp = _make_descriptor(adir, nonce="abc", bound_key="S")
    srv = FakeServer(sp, wire.response_frame(ok=True, stdout="INJECTED"))
    _patch_registry(monkeypatch, base)
    try:
        rc, out = _run(monkeypatch, {"session_id": "S", "hook_event_name": "SessionStart"})
        assert rc == 0 and out == "INJECTED"
        assert srv.received[0]["key"] == "S"
    finally:
        srv.close()


def test_run_buffers_subagent_when_ambiguous(tmp_path, monkeypatch):
    base = tmp_path / "base"
    base.mkdir(mode=0o700)
    adir = base / "100-200"
    adir.mkdir(mode=0o700)
    _make_descriptor(adir, nonce="s1", bound_key=None)
    _make_descriptor(adir, nonce="s2", bound_key=None)  # 2 unbound -> ambiguous
    _patch_registry(monkeypatch, base)
    rc, out = _run(
        monkeypatch, {"session_id": "P", "agent_id": "A", "hook_event_name": "SubagentStart"}
    )
    assert rc == 0 and out == ""
    frames = rz.claim_pending(adir, "A", "tok")  # buffered under own-identity key "A"
    assert len(frames) == 1
    req = json.loads(frames[0][struct.calcsize(">I") :].decode("utf-8"))
    assert req["key"] == "A" and req["payload"]["agent_id"] == "A"


def test_run_safe_noop_for_ambiguous_tool_event(tmp_path, monkeypatch):
    base = tmp_path / "base"
    base.mkdir(mode=0o700)
    adir = base / "100-200"
    adir.mkdir(mode=0o700)
    _make_descriptor(adir, nonce="s1", bound_key=None)
    _make_descriptor(adir, nonce="s2", bound_key=None)
    _patch_registry(monkeypatch, base)
    # codex tool event: no agent_id -> key is parent "P"; ambiguous -> NEVER buffer under "P"
    rc, out = _run(monkeypatch, {"session_id": "P", "hook_event_name": "PreToolUse"})
    assert rc == 0 and out == ""
    assert rz.claim_pending(adir, "P", "tok") == []


def test_run_no_descriptors_is_noop(tmp_path, monkeypatch):
    base = tmp_path / "base"
    base.mkdir(mode=0o700)
    (base / "100-200").mkdir(mode=0o700)
    _patch_registry(monkeypatch, base)
    rc, out = _run(monkeypatch, {"session_id": "S", "hook_event_name": "SessionStart"})
    assert rc == 0 and out == ""


def test_run_empty_stdin_is_noop(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert shim.run_from_args(_args()) == 0
