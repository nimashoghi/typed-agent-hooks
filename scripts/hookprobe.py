#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=3.3,<3.4"]
# ///
"""M0 verification probe for typed-agent-hooks[fastmcp] (gates G1/G2/G3).

A throwaway FastMCP **stdio** server that records, per tool call, the MCP request
``_meta`` (especially Codex's ``threadId``) as reached from BOTH an
``on_call_tool`` middleware (the path the bridge will use) and the tool's
``Context``, plus the ``CLAUDE_*``/``CODEX_*`` environment seen at lifespan start.

Register it as an MCP server in a real Codex AND a real Claude Code session, ask
the agent to call ``ping`` (from the main agent and a subagent), then read the
log to confirm:

  G1 (Claude): ``CLAUDE_CODE_SESSION_ID`` present in lifespan_start.env AND equal
              to the hook payload ``session_id``.
  G2 (Codex):  ``threadId`` present in on_call_tool.middleware_meta AND equal to
              the hook ``session_id`` (root) / ``agent_id`` (ThreadSpawn subagent).
  G3 (Codex):  the FIRST ping already carries a non-null threadId.

Run:  uv run scripts/hookprobe.py        (or chmod +x and run directly)
Log:  $HOOKPROBE_LOG or /tmp/hookprobe.log   (one JSON object per line)
"""

from __future__ import annotations

import json
import os
import sys
import time
from contextlib import asynccontextmanager

LOG = os.environ.get("HOOKPROBE_LOG", "/tmp/hookprobe.log")


def _log(record: dict) -> None:
    record = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), **record}
    try:
        with open(LOG, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception:
        pass


def _harness_env() -> dict:
    return {
        k: v
        for k, v in os.environ.items()
        if k.startswith("CLAUDE") or k.startswith("CODEX") or k == "CLAUDECODE"
    }


def _meta_view(ctx) -> dict:
    """Best-effort: pull the request _meta (threadId + full dump) from a Context."""
    out: dict = {"threadId": None, "meta_dump": None, "error": None}
    try:
        rc = getattr(ctx, "request_context", None)
        meta = getattr(rc, "meta", None) if rc is not None else None
        if meta is None:
            out["error"] = "no request_context.meta"
            return out
        out["threadId"] = getattr(meta, "threadId", None)
        dump = getattr(meta, "model_dump", None)
        out["meta_dump"] = dump(by_alias=True) if callable(dump) else str(meta)
    except Exception as exc:  # never crash the server
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


from fastmcp import FastMCP  # noqa: E402

# Middleware base — import defensively across fastmcp layouts.
try:
    from fastmcp.server.middleware import Middleware  # type: ignore  # noqa: E402
except Exception:  # pragma: no cover
    from fastmcp.server.middleware.middleware import Middleware  # type: ignore  # noqa: E402


@asynccontextmanager
async def _lifespan(server):
    # G1: capture the env the server actually sees at startup (custom-lifespan
    # path, mirroring IPi's create_server which passes a custom lifespan).
    _log(
        {"event": "lifespan_start", "pid": os.getpid(), "ppid": os.getppid(), "env": _harness_env()}
    )
    try:
        yield {"hookprobe": True}
    finally:
        _log({"event": "lifespan_stop", "pid": os.getpid()})


class _Capture(Middleware):
    async def on_call_tool(self, context, call_next):
        fctx = getattr(context, "fastmcp_context", None)
        rec: dict = {"event": "on_call_tool", "pid": os.getpid()}
        rec["middleware_meta"] = (
            _meta_view(fctx) if fctx is not None else {"error": "no fastmcp_context"}
        )
        try:
            rec["tool_name"] = getattr(getattr(context, "message", None), "name", None)
        except Exception:
            rec["tool_name"] = None
        _log(rec)
        return await call_next(context)


mcp = FastMCP("hookprobe", lifespan=_lifespan)
mcp.add_middleware(_Capture())


@mcp.tool
def ping(note: str = "") -> str:
    """Diagnostic ping: records the MCP request _meta (threadId) + env, returns it."""
    rec: dict = {"event": "tool_ping", "pid": os.getpid(), "note": note, "env": _harness_env()}
    tid = None
    try:
        from fastmcp.server.dependencies import get_context  # lazy

        view = _meta_view(get_context())
        rec["tool_meta"] = view
        tid = view.get("threadId")
    except Exception as exc:
        rec["tool_meta"] = {"error": f"{type(exc).__name__}: {exc}"}
    _log(rec)
    return f"pong note={note!r} threadId={tid} pid={os.getpid()}"


if __name__ == "__main__":
    _log({"event": "boot", "pid": os.getpid(), "ppid": os.getppid(), "argv": sys.argv})
    mcp.run()
