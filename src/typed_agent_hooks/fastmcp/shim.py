"""Stdlib-only forward shim: a harness command-hook -> the running bridge.

Reads the hook JSON on stdin, finds the correct running server via the registry
(:mod:`typed_agent_hooks.fastmcp.rendezvous`), forwards ``{provider, payload}``
over its unix socket, prints the server's ``stdout``, and **always exits 0**.

Fail-open is the contract: a missing / slow / dead / ambiguous server must never
block the harness or corrupt routing. Imports **no** ``fastmcp``.

Resolution ladder (see the plan, §2.3):
  (a) EXACT      bound_key == correlation_key (newest live wins) -> forward
  (b) SINGLE     exactly one live descriptor -> forward
  (c) UNROUTABLE >=2 live, no exact match:
        - own-identity event (codex Subagent{Start,Stop}) -> buffer-and-resolve
        - otherwise (ambiguous codex tool event) -> safe no-op
  (d) NONE       -> fail-open
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
from pathlib import Path
from typing import NamedTuple

from . import rendezvous as rz
from . import wire

# Codex events whose correlation key IS the (sub)agent's own identity (agent_id),
# so an ambiguous resolution may safely buffer under that key for the server that
# later binds it. (Tool events lack agent_id -> their key is the parent session_id
# -> they must NOT be buffered/guessed; they safe-no-op.)
_OWN_IDENTITY_EVENTS = frozenset({"SubagentStart", "SubagentStop"})

_CONNECT_RETRIES = 5
_CONNECT_RETRY_SLEEP = 0.05  # listener-start race window
_FORWARD_TIMEOUT = 2.0
_MAX_RESOLVE_ATTEMPTS = 2  # re-resolve once after pruning a stale descriptor

# Events fired at session/subagent start, when the server (and its bridge) may
# still be launching. For these, briefly wait for a descriptor to appear so the
# startup event isn't silently dropped (the SessionStart-before-MCP race). Other
# events never wait: a missing server mid-session is an immediate no-op.
_STARTUP_EVENTS = frozenset({"SessionStart", "SubagentStart"})
_STARTUP_WAIT_ENV = "TAH_FORWARD_STARTUP_WAIT_S"
_STARTUP_WAIT_S = 5.0  # override via $TAH_FORWARD_STARTUP_WAIT_S (0 disables)
_STARTUP_POLL_SLEEP = 0.1


class _Forward(NamedTuple):
    connected: bool
    out: str | None


def add_forward_arguments(parser: argparse.ArgumentParser) -> None:
    """Wire the ``forward`` arguments (shared by the CLI subcommand + console script)."""
    parser.add_argument("--provider", required=True, choices=["codex", "claude-code"])
    parser.add_argument("--server-name", dest="server_name", default="ipi")
    # carried so the installed command is marker-managed (see hooksets/install.py);
    # not used for routing.
    parser.add_argument("--hookset-name", dest="hookset_name", default=None)
    parser.add_argument("--registry-root", dest="registry_root", default=None)


def run_from_args(args: argparse.Namespace) -> int:
    """Entry point for the ``forward`` subcommand. NEVER raises; always returns 0."""
    with contextlib.suppress(Exception):
        _run(args)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point (``tah-fastmcp-forward``)."""
    parser = argparse.ArgumentParser(prog="tah-fastmcp-forward")
    add_forward_arguments(parser)
    return run_from_args(parser.parse_args(argv))


def _read_stdin_event() -> dict | None:
    try:
        data = sys.stdin.read()
    except Exception:
        return None
    if not data.strip():
        return None
    try:
        obj = json.loads(data)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _live_descriptors(adir: Path, server_name: str) -> list[dict]:
    return [
        d
        for d in rz.list_descriptors(adir)
        if d.get("server_name") == server_name and rz.descriptor_is_live(d)
    ]


def _startup_wait_seconds() -> float:
    raw = os.environ.get(_STARTUP_WAIT_ENV)
    if raw is None:
        return _STARTUP_WAIT_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        return _STARTUP_WAIT_S


def _await_startup_descriptor(adir: Path, server_name: str) -> None:
    """On a session/subagent-start event, briefly wait for the server's descriptor.

    The server (and its bridge) may still be launching when the harness fires the
    startup hook; polling for a live descriptor lets the event be delivered once
    the server is up instead of being dropped. Bounded by
    ``$TAH_FORWARD_STARTUP_WAIT_S`` (default 5s; 0 disables). Exits as soon as a
    descriptor appears.
    """

    wait = _startup_wait_seconds()
    if wait <= 0.0 or _live_descriptors(adir, server_name):
        return
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        time.sleep(_STARTUP_POLL_SLEEP)
        if _live_descriptors(adir, server_name):
            return


def _is_own_identity_event(provider: str, event: dict) -> bool:
    if provider != "codex":
        return False
    agent_id = event.get("agent_id")
    return (
        isinstance(agent_id, str)
        and bool(agent_id)
        and event.get("hook_event_name") in _OWN_IDENTITY_EVENTS
    )


def _resolve(descs: list[dict], key: str | None) -> dict | None:
    """Pick a descriptor: exact bound_key match (newest live wins), else the sole
    descriptor, else ``None`` (ambiguous)."""
    if key is not None:
        exact = [d for d in descs if d.get("bound_key") == key]
        if exact:
            exact.sort(
                key=lambda d: (d.get("generation") or 0, d.get("starttime") or 0), reverse=True
            )
            return exact[0]
    if len(descs) == 1:
        return descs[0]
    return None


def _forward(desc: dict, *, key: str, provider: str, payload: dict) -> _Forward:
    sock_path = desc.get("socket_path")
    nonce = desc.get("server_nonce")
    if not isinstance(sock_path, str) or not isinstance(nonce, str):
        return _Forward(False, None)

    sock = None
    for _ in range(_CONNECT_RETRIES):
        sock = rz.connect_unix(sock_path, timeout=_FORWARD_TIMEOUT)
        if sock is not None:
            break
        time.sleep(_CONNECT_RETRY_SLEEP)
    if sock is None:
        rz.prune_descriptor(desc)  # pre-connect failure: stale -> prune, caller re-resolves
        return _Forward(False, None)

    try:
        puid = rz.peer_uid(sock)
        if puid is not None and puid != os.geteuid():
            return _Forward(True, None)
        wire.send_frame(
            sock,
            wire.request_frame(key=key, provider=provider, server_nonce=nonce, payload=payload),
        )
        resp = wire.recv_frame(sock)
    except Exception:
        return _Forward(True, None)  # post-connect failure: no-op, NO retry (avoid double-dispatch)
    finally:
        with contextlib.suppress(Exception):
            sock.close()

    if isinstance(resp, dict):
        out = resp.get("stdout")
        if isinstance(out, str) and out:
            return _Forward(True, out)
    return _Forward(True, None)


def _run(args: argparse.Namespace) -> None:
    provider = args.provider.replace("-", "_")
    event = _read_stdin_event()
    if event is None:
        return
    key = wire.correlation_key(provider, event)

    base = rz.runtime_base(explicit=Path(args.registry_root) if args.registry_root else None)
    if base is None:
        return
    with contextlib.suppress(Exception):
        rz.sweep_base(base)  # bounded opportunistic GC
    anchor = rz.find_harness_anchor()
    if anchor is None:
        return
    adir = rz.anchor_dir(base, anchor)

    if event.get("hook_event_name") in _STARTUP_EVENTS:
        _await_startup_descriptor(adir, args.server_name)

    for _ in range(_MAX_RESOLVE_ATTEMPTS):
        descs = _live_descriptors(adir, args.server_name)
        if not descs:
            return
        target = _resolve(descs, key)
        if target is not None:
            result = _forward(target, key=key or "", provider=provider, payload=event)
            if result.connected:
                if result.out is not None:
                    sys.stdout.write(result.out)
                return
            continue  # connect failed (descriptor pruned) -> re-resolve once
        # ambiguous (>=2 live, no exact match)
        if key is not None and _is_own_identity_event(provider, event):
            frame = wire.encode_frame(
                wire.request_frame(key=key, provider=provider, server_nonce="", payload=event)
            )
            rz.enqueue_pending(adir, key, frame)
        return  # buffered or safe no-op
