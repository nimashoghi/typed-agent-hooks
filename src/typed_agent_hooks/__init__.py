"""Code-first hook APIs for Codex, Claude Code, and shared semantics."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from . import claude_code, codex, shared
    from .collection import Collection

__all__ = ["Collection", "claude_code", "codex", "shared"]
__version__ = "0.1.0"


def __getattr__(name: str) -> Any:
    """Load public surfaces only when a caller selects them."""

    if name == "Collection":
        from .collection import Collection

        globals()[name] = Collection
        return Collection
    if name in {"claude_code", "codex", "shared"}:
        module = import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
