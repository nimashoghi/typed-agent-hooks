"""Explicit provider-independent semantic event and output layer."""

from . import adapters, events, outputs
from .adapters import (
    NoSharedMappingError,
    from_claude_code,
    from_codex,
    parse_claude_code,
    parse_codex,
    try_from_claude_code,
)
from .app import HookApp

__all__ = [
    "HookApp",
    "NoSharedMappingError",
    "adapters",
    "events",
    "from_claude_code",
    "from_codex",
    "outputs",
    "parse_claude_code",
    "parse_codex",
    "try_from_claude_code",
]
