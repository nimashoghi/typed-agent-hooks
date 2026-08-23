"""Fail-open forwarder from one harness command hook to the running bridge.

Reads the hook JSON on stdin, finds the correct running server via the registry
(:mod:`typed_agent_hooks.fastmcp.rendezvous`), forwards ``{provider, payload}``
over its unix socket, prints the server's ``stdout``, and **always exits 0**.

Fail-open is the contract: a missing / slow / dead / ambiguous server must never
block the harness or corrupt routing. Imports no ``fastmcp``.

Resolution ladder (see the plan, §2.3):
  (a) EXACT      bound_key == correlation_key (newest live wins) -> forward
  (b) SINGLE     exactly one live descriptor -> forward
  (c) UNROUTABLE >=2 live, no exact match:
        - own-identity event (codex Subagent{Start,Stop}) -> buffer-and-resolve
        - otherwise (ambiguous codex tool event) -> safe no-op
  (d) NONE       -> fail-open
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Annotated, NamedTuple, TypeAlias

from cyclopts import App, Parameter

from typed_agent_hooks.config import ProviderName

from . import rendezvous as rz
from . import wire

# Codex events whose correlation key IS the (sub)agent's own identity (agent_id),
# so an ambiguous resolution may safely buffer under that key for the server that
# later binds it. (Tool events lack agent_id -> their key is the parent session_id
# -> they must NOT be buffered/guessed; they safe-no-op.)
_OWN_IDENTITY_EVENTS = frozenset({"SubagentStart", "SubagentStop"})

_CONNECT_RETRIES = 5
_CONNECT_RETRY_SLEEP = 0.05  # listener-start race window
_DEFAULT_RESPONSE_TIMEOUT = 2.0
_MAX_RESOLVE_ATTEMPTS = 2  # re-resolve once after pruning a stale descriptor

# Events fired at session/subagent start, when the server (and its bridge) may
# still be launching. For these, briefly wait for a descriptor to appear so the
# startup event isn't silently dropped (the SessionStart-before-MCP race). Other
# events never wait: a missing server mid-session is an immediate no-op.
_STARTUP_EVENTS = frozenset({"SessionStart", "SubagentStart"})
_STARTUP_WAIT_ENV = "TAH_FORWARD_STARTUP_WAIT_S"
_STARTUP_WAIT_S = 60.0  # override via $TAH_FORWARD_STARTUP_WAIT_S (0 disables)
_STARTUP_POLL_SLEEP = 0.1


class _Forward(NamedTuple):
    connected: bool
    out: str | None


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


def _payload_from_token(_type: object, tokens: list[object]) -> dict[str, object] | None:
    raw = getattr(tokens[0], "value", "")
    if raw == "-":
        return _read_stdin_event()
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return decoded if isinstance(decoded, dict) else None


Payload: TypeAlias = Annotated[
    dict[str, object] | None,
    Parameter(
        n_tokens=1,
        converter=_payload_from_token,
        accepts_keys=False,
        allow_leading_hyphen=True,
    ),
]
app = App(name="tah-fastmcp-forward", result_action="print_non_none_return_zero")


@app.default
def forward(
    payload: Payload,
    *,
    provider: ProviderName,
    server_name: str = "ipi",
    managed_app: str | None = None,
    registry_root: Path | None = None,
    startup_wait: float | None = None,
    response_timeout: float = _DEFAULT_RESPONSE_TIMEOUT,
) -> str | None:
    """Forward one provider hook payload to its running local bridge.

    Parameters
    ----------
    payload:
        Provider JSON object, or ``-`` in the CLI to read it from stdin.
    provider:
        Provider that emitted the payload.
    server_name:
        Running bridge name.
    managed_app:
        Stable config ownership marker; it does not affect routing.
    registry_root:
        Explicit rendezvous registry root.
    startup_wait:
        Seconds to wait for a bridge on startup events.
    response_timeout:
        Seconds to wait for the bridge response.
    """

    del managed_app
    if startup_wait is not None and (not math.isfinite(startup_wait) or startup_wait < 0):
        raise ValueError("startup_wait must be finite and non-negative")
    if not math.isfinite(response_timeout) or response_timeout <= 0:
        raise ValueError("response_timeout must be finite and positive")
    if payload is None:
        return None
    with contextlib.suppress(Exception):
        return _run(
            payload,
            provider=provider,
            server_name=server_name,
            registry_root=registry_root,
            startup_wait=startup_wait,
            response_timeout=response_timeout,
        )
    return None


def _live_descriptors(adir: Path, server_name: str) -> list[dict]:
    return [
        d
        for d in rz.list_descriptors(adir)
        if d.get("server_name") == server_name and rz.descriptor_is_live(d)
    ]


def _startup_wait_seconds(explicit: float | None = None) -> float:
    if explicit is not None:
        return explicit
    raw = os.environ.get(_STARTUP_WAIT_ENV)
    if raw is None:
        return _STARTUP_WAIT_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        return _STARTUP_WAIT_S


def _await_startup_descriptor(
    adir: Path,
    server_name: str,
    *,
    wait_seconds: float | None = None,
) -> None:
    """On a session/subagent-start event, briefly wait for the server's descriptor.

    The server (and its bridge) may still be launching when the harness fires the
    startup hook; polling for a live descriptor lets the event be delivered once
    the server is up instead of being dropped. Bounded by
    ``$TAH_FORWARD_STARTUP_WAIT_S`` (default 60s; 0 disables). Exits as soon as a
    descriptor appears.
    """

    wait = _startup_wait_seconds(wait_seconds)
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


def _forward(
    desc: dict,
    *,
    key: str,
    provider: str,
    payload: dict,
    response_timeout: float = _DEFAULT_RESPONSE_TIMEOUT,
) -> _Forward:
    sock_path = desc.get("socket_path")
    nonce = desc.get("server_nonce")
    if not isinstance(sock_path, str) or not isinstance(nonce, str):
        return _Forward(False, None)

    sock = None
    for _ in range(_CONNECT_RETRIES):
        sock = rz.connect_unix(sock_path, timeout=response_timeout)
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


def _run(
    event: dict[str, object],
    *,
    provider: str,
    server_name: str,
    registry_root: Path | None,
    startup_wait: float | None,
    response_timeout: float,
) -> str | None:
    key = wire.correlation_key(provider, event)

    base = rz.runtime_base(explicit=registry_root)
    if base is None:
        return None
    with contextlib.suppress(Exception):
        rz.sweep_base(base)  # bounded opportunistic GC
    anchor = rz.find_harness_anchor()
    if anchor is None:
        return None
    adir = rz.anchor_dir(base, anchor)

    if event.get("hook_event_name") in _STARTUP_EVENTS:
        _await_startup_descriptor(
            adir,
            server_name,
            wait_seconds=startup_wait,
        )

    for _ in range(_MAX_RESOLVE_ATTEMPTS):
        descs = _live_descriptors(adir, server_name)
        if not descs:
            return None
        target = _resolve(descs, key)
        if target is not None:
            result = _forward(
                target,
                key=key or "",
                provider=provider,
                payload=event,
                response_timeout=response_timeout,
            )
            if result.connected:
                return result.out
            continue  # connect failed (descriptor pruned) -> re-resolve once
        # ambiguous (>=2 live, no exact match)
        if key is not None and _is_own_identity_event(provider, event):
            frame = wire.encode_frame(
                wire.request_frame(key=key, provider=provider, server_nonce="", payload=event)
            )
            rz.enqueue_pending(adir, key, frame)
        return None  # buffered or safe no-op
    return None
