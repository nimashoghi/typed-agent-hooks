"""Claude Code command-hook wire schemas."""

from . import events, outputs
from .events import INPUT_TYPES, parse_input
from .outputs import render_output

__all__ = ["INPUT_TYPES", "events", "outputs", "parse_input", "render_output"]
