"""Host-independent hook events, outputs and the hook runner."""

from . import adapters, events, outputs
from .adapters import (
    NoSharedMappingError,
    from_claude_code,
    from_codex,
    native_event_name,
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
    "native_event_name",
    "outputs",
    "parse_claude_code",
    "parse_codex",
    "try_from_claude_code",
]
