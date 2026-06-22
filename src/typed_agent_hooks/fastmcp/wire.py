"""Stdlib-only wire protocol + correlation key for the FastMCP bridge.

Shared by the shim (client) and the bridge (server). Imports nothing beyond the
standard library so it runs in the harness's hook subprocess regardless of what
is installed there. The bridge does async framing on top of :func:`encode_frame`.

Framing: a 4-byte big-endian unsigned length prefix followed by that many bytes
of UTF-8 JSON. Exactly one request frame then one response frame per connection.
"""

from __future__ import annotations

import json
import socket
import struct
from collections.abc import Mapping
from typing import Any

PROTOCOL_VERSION = 1
_HEADER = struct.Struct(">I")
MAX_FRAME_BYTES = 32 * 1024 * 1024  # guard against a bogus/hostile length prefix


def encode_frame(obj: Any) -> bytes:
    """Serialize ``obj`` to a length-prefixed UTF-8 JSON frame."""
    body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
    if len(body) > MAX_FRAME_BYTES:
        raise ValueError("frame body exceeds MAX_FRAME_BYTES")
    return _HEADER.pack(len(body)) + body


def decode_body(length: int, body: bytes) -> Any:
    if length > MAX_FRAME_BYTES:
        raise ValueError("frame length exceeds MAX_FRAME_BYTES")
    return json.loads(body.decode("utf-8"))


def _recv_exactly(sock: socket.socket, n: int) -> bytes:
    chunks: list[bytes] = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("socket closed mid-frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def send_frame(sock: socket.socket, obj: Any) -> None:
    sock.sendall(encode_frame(obj))


def recv_frame(sock: socket.socket) -> Any:
    (length,) = _HEADER.unpack(_recv_exactly(sock, _HEADER.size))
    if length > MAX_FRAME_BYTES:
        raise ValueError("frame length exceeds MAX_FRAME_BYTES")
    body = _recv_exactly(sock, length) if length else b""
    return decode_body(length, body)


def header_size() -> int:
    return _HEADER.size


def unpack_length(header: bytes) -> int:
    (length,) = _HEADER.unpack(header)
    return length


def request_frame(*, key: str, provider: str, server_nonce: str, payload: Any) -> dict:
    """Build the shim->server request envelope."""
    return {
        "v": PROTOCOL_VERSION,
        "key": key,
        "provider": provider,
        "server_nonce": server_nonce,
        "payload": payload,
    }


def response_frame(*, ok: bool, stdout: str | None = None, exit_code: int = 0) -> dict:
    """Build the server->shim response envelope (``stdout`` ``None`` -> empty string)."""
    return {"v": PROTOCOL_VERSION, "ok": ok, "stdout": stdout or "", "exit": exit_code}


def correlation_key(provider: str, event: Mapping[str, Any]) -> str | None:
    """Provider-aware rendezvous key, or ``None`` if it cannot be computed.

    - **claude_code**: ``session_id`` (one server per top-level session; subagents
      share it; the in-server HookApp branches on ``agent_id`` internally).
    - **codex**: ``agent_id`` when present (only on ``Subagent{Start,Stop}``, where
      it equals the subagent's ``thread_id``), else ``session_id`` (the root /
      parent thread id, which equals ``_meta.threadId`` for the root server).

    Returning ``None`` makes the shim fail open. NOTE: a Codex subagent *tool*
    event has no ``agent_id`` and ``session_id`` is the parent's, so its key does
    **not** identify the subagent's own server; the shim must therefore treat
    such ambiguous codex tool events as unroutable (never single-server / buffer)
    — see :mod:`typed_agent_hooks.fastmcp.shim`.
    """
    session_id = event.get("session_id")
    session_id = session_id if isinstance(session_id, str) and session_id else None
    if provider == "claude_code":
        return session_id
    if provider == "codex":
        agent_id = event.get("agent_id")
        if isinstance(agent_id, str) and agent_id:
            return agent_id
        return session_id
    return None
