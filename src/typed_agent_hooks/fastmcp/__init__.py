"""typed-agent-hooks FastMCP hook->server bridge (optional ``[fastmcp]`` extra).

Two roles share this subpackage:

- **Forwarder** (``shim``/``rendezvous``/``wire``): imports Cyclopts but no
  ``fastmcp``. Runs in the harness's hook subprocess.
- **Bridge** (``bridge``): server-side; imports ``fastmcp``. Installed in-process by
  a FastMCP stdio server via ``attach``.

``HookBridge``/``attach`` are exposed lazily so that importing this package from
the forwarding process never requires ``fastmcp``.
"""

from __future__ import annotations

from .config import ForwardingHooks
from .launcher import forward_command
from .shim import forward

__all__ = ["ForwardingHooks", "HookBridge", "attach", "forward", "forward_command"]


def __getattr__(name: str):  # PEP 562 lazy export — keeps the shim path fastmcp-free
    if name in ("HookBridge", "attach"):
        from . import bridge

        return getattr(bridge, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
