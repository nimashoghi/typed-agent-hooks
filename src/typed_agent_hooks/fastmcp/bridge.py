"""Server-side FastMCP bridge: receive forwarded harness hook events in-process.

``HookBridge.attach(server, hook_app, provider=...)`` wraps a FastMCP **stdio**
server so that, on the serving event loop, it:

  * installs an ``on_call_tool`` middleware that reads Codex's ``_meta.threadId``
    and binds this server to that thread id (Claude binds eagerly from the
    ``CLAUDE_CODE_SESSION_ID`` env var instead),
  * listens on a per-server unix socket and dispatches each forwarded event
    through the given typed-agent-hooks ``HookApp`` (off-loop, in an executor, so
    a handler may call back into the loop for async server state and a slow
    handler can never hang the harness),
  * registers/cleans a descriptor in the rendezvous registry.

This module is the ONLY part of the subpackage that imports ``fastmcp`` (provided
by the ``[fastmcp]`` extra). If no harness ancestor is found (e.g. an HTTP server
not launched by the harness), the bridge stays an inactive no-op and the server
serves tools normally.
"""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from typed_agent_hooks.core import Provider

from . import rendezvous as rz
from . import wire

try:  # the [fastmcp] extra
    from fastmcp.server.middleware import Middleware
except Exception:  # pragma: no cover
    from fastmcp.server.middleware.middleware import Middleware

_DISPATCH_TIMEOUT = 30.0  # a slow/blocked handler returns no-op rather than hanging
_PROVIDERS = ("codex", "claude_code", "shared")


class _ThreadIdCapture(Middleware):
    """Read ``_meta.threadId`` off each tool call and bind the server (Codex)."""

    def __init__(self, bridge: HookBridge) -> None:
        self._bridge = bridge

    async def on_call_tool(self, context: Any, call_next: Any) -> Any:
        with contextlib.suppress(Exception):
            fctx = getattr(context, "fastmcp_context", None)
            rc = getattr(fctx, "request_context", None) if fctx is not None else None
            meta = getattr(rc, "meta", None) if rc is not None else None
            tid = getattr(meta, "threadId", None) if meta is not None else None
            if isinstance(tid, str) and tid:
                self._bridge._maybe_bind(tid)
        return await call_next(context)


class HookBridge:
    """Handle returned by :func:`attach`; lifecycle is bound to the server lifespan."""

    def __init__(
        self,
        server: Any,
        hook_app: Any,
        *,
        provider: str,
        server_name: str,
        registry_root: str | Path | None,
    ) -> None:
        if provider not in _PROVIDERS:
            raise ValueError(f"provider must be one of {_PROVIDERS}, got {provider!r}")
        self._server = server
        self._app = hook_app
        self._provider = provider
        self._server_name = server_name
        self._registry_root = Path(registry_root) if registry_root is not None else None
        self._nonce = rz.new_nonce()
        self._generation = 1
        self._loop: asyncio.AbstractEventLoop | None = None
        self._anchor_dir: Path | None = None
        self._descriptor: rz.Descriptor | None = None
        self._listener: Any = None
        self._writers: set[Any] = set()

    @staticmethod
    def attach(
        server: Any,
        hook_app: Any,
        *,
        provider: str,
        server_name: str = "ipi",
        registry_root: str | Path | None = None,
    ) -> HookBridge:
        bridge = HookBridge(
            server,
            hook_app,
            provider=provider,
            server_name=server_name,
            registry_root=registry_root,
        )
        bridge._install()
        return bridge

    # -- wiring ----------------------------------------------------------------

    def _install(self) -> None:
        if not hasattr(self._server, "_lifespan"):
            raise RuntimeError("FastMCP server has no _lifespan; unsupported fastmcp version")
        original = self._server._lifespan
        self._server.add_middleware(_ThreadIdCapture(self))

        @asynccontextmanager
        async def wrapped(server: Any):
            async with original(server) as result:  # preserve _lifespan_result bookkeeping
                await self._startup()
                try:
                    yield result  # yield the ORIGINAL lifespan result unchanged
                finally:
                    await self._teardown()

        self._server._lifespan = wrapped

    async def _startup(self) -> None:
        self._loop = asyncio.get_running_loop()  # backend assertion (must be asyncio)
        base = rz.runtime_base(explicit=self._registry_root)
        anchor = rz.find_harness_anchor()
        if base is None or anchor is None:
            return  # no rendezvous possible (e.g. HTTP / not a harness child) -> inactive
        adir = rz.ensure_anchor_dir(base, anchor)
        if adir is None:
            return
        self._anchor_dir = adir

        sock_path = str(rz.socket_path(adir, self._nonce))
        with contextlib.suppress(FileNotFoundError):
            os.unlink(sock_path)
        self._listener = await asyncio.start_unix_server(self._handle_conn, path=sock_path)
        with contextlib.suppress(OSError):
            os.chmod(sock_path, 0o600)  # do not trust umask

        st = rz.read_proc_stat(os.getpid())
        bound_key = os.environ.get("CLAUDE_CODE_SESSION_ID") or None
        self._descriptor = rz.Descriptor(
            server_nonce=self._nonce,
            socket_path=sock_path,
            bound_key=bound_key,
            pid=os.getpid(),
            starttime=st[1] if st else 0,
            generation=self._generation,
            cwd=os.getcwd(),
            provider=self._provider,
            server_name=self._server_name,
        )
        rz.write_descriptor(adir, self._descriptor)
        atexit.register(self._atexit_cleanup)  # best-effort backstop for non-clean exits
        if bound_key is not None:
            self._drain(bound_key)

    async def _teardown(self) -> None:
        if self._listener is not None:
            self._listener.close()
            with contextlib.suppress(Exception):
                await self._listener.wait_closed()
        for w in list(self._writers):
            with contextlib.suppress(Exception):
                w.close()
        self._atexit_cleanup()

    def _atexit_cleanup(self) -> None:
        if self._descriptor is None or self._anchor_dir is None:
            return
        rz.prune_descriptor(
            {
                "socket_path": self._descriptor.socket_path,
                "_path": str(rz.descriptor_path(self._anchor_dir, self._nonce)),
            }
        )

    # -- binding ---------------------------------------------------------------

    def _maybe_bind(self, thread_id: str) -> None:
        """Bind this server to ``thread_id`` once (idempotent). Called on the loop."""
        if self._descriptor is None or self._anchor_dir is None:
            return
        if self._descriptor.bound_key is not None:
            return
        self._descriptor.bound_key = thread_id
        self._generation += 1
        self._descriptor.generation = self._generation
        with contextlib.suppress(Exception):
            rz.write_descriptor(self._anchor_dir, self._descriptor)
        self._drain(thread_id)

    def _drain(self, key: str) -> None:
        """Single-owner claim of buffered events for ``key`` -> async dispatch."""
        if self._anchor_dir is None or self._loop is None:
            return
        for frame in rz.claim_pending(self._anchor_dir, key, self._nonce):
            req = _decode_frame(frame)
            if not isinstance(req, dict):
                continue
            payload = req.get("payload")
            if isinstance(payload, dict):
                self._loop.create_task(self._dispatch_quiet(payload, req.get("provider")))

    # -- dispatch --------------------------------------------------------------

    async def _dispatch_quiet(self, payload: dict, fwd_provider: Any) -> None:
        with contextlib.suppress(Exception):
            await self._dispatch(payload, fwd_provider)

    async def _dispatch(self, payload: dict, fwd_provider: Any) -> str | None:
        loop = asyncio.get_running_loop()

        def _call() -> str | None:
            if self._provider == "shared":
                return self._app.handle_json(Provider(fwd_provider), payload)
            return self._app.handle_json(payload)

        # Run the (sync) HookApp off the loop: keeps the loop responsive, lets a
        # handler call back into the loop for async state, and bounds the time.
        return await asyncio.wait_for(loop.run_in_executor(None, _call), _DISPATCH_TIMEOUT)

    # -- socket handler --------------------------------------------------------

    async def _handle_conn(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._writers.add(writer)
        try:
            sock = writer.get_extra_info("socket")
            if sock is not None:
                puid = rz.peer_uid(sock)
                if puid is not None and puid != os.geteuid():
                    return  # cross-uid: refuse before dispatch
            req = await _read_frame_async(reader)
            ok, out = True, None
            if not isinstance(req, dict) or req.get("server_nonce") != self._nonce:
                ok = False  # nonce is the auth: only a reader of our 0700 descriptor has it
            else:
                payload = req.get("payload")
                if isinstance(payload, dict):
                    try:
                        out = await self._dispatch(payload, req.get("provider"))
                    except Exception:
                        ok, out = False, None
                else:
                    ok = False
            await _write_frame_async(writer, wire.response_frame(ok=ok, stdout=out))
        except Exception:
            with contextlib.suppress(Exception):
                await _write_frame_async(writer, wire.response_frame(ok=False, stdout=None))
        finally:
            self._writers.discard(writer)
            with contextlib.suppress(Exception):
                writer.close()


def attach(
    server: Any,
    hook_app: Any,
    *,
    provider: str,
    server_name: str = "ipi",
    registry_root: str | Path | None = None,
) -> HookBridge:
    """Attach a :class:`HookBridge` to a FastMCP stdio server (after create, before run)."""
    return HookBridge.attach(
        server, hook_app, provider=provider, server_name=server_name, registry_root=registry_root
    )


# --- async framing (on top of the stdlib wire helpers) ------------------------


def _decode_frame(frame: bytes) -> Any:
    hs = wire.header_size()
    if len(frame) < hs:
        return None
    length = wire.unpack_length(frame[:hs])
    with contextlib.suppress(Exception):
        return wire.decode_body(length, frame[hs : hs + length])
    return None


async def _read_frame_async(reader: asyncio.StreamReader) -> Any:
    header = await reader.readexactly(wire.header_size())
    length = wire.unpack_length(header)
    if length > wire.MAX_FRAME_BYTES:
        raise ValueError("frame length exceeds MAX_FRAME_BYTES")
    body = await reader.readexactly(length) if length else b""
    return wire.decode_body(length, body)


async def _write_frame_async(writer: asyncio.StreamWriter, obj: Any) -> None:
    writer.write(wire.encode_frame(obj))
    await writer.drain()
