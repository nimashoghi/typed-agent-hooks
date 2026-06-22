"""typed-agent-hooks FastMCP hook->server bridge (optional ``[fastmcp]`` extra).

Two roles share this subpackage:

- **Shim** (``shim``/``rendezvous``/``wire``): stdlib + ``/proc`` only, imports **no**
  ``fastmcp`` (and no codex/claude). Runs in the harness's hook subprocess.
- **Bridge** (``bridge``): server-side; imports ``fastmcp``. Installed in-process by
  a FastMCP stdio server via ``attach``.

``HookBridge``/``attach`` are exposed lazily so that importing this package (or its
stdlib submodules, e.g. from the shim) never hard-requires ``fastmcp``.
"""

from __future__ import annotations

__all__ = ["HookBridge", "attach"]


def __getattr__(name: str):  # PEP 562 lazy export — keeps the shim path fastmcp-free
    if name in ("HookBridge", "attach"):
        from . import bridge

        return getattr(bridge, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
