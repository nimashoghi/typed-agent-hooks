"""Claude Code command-hook wire schemas."""

from . import events, outputs
from .events import parse_input
from .outputs import render_output

__all__ = ["events", "outputs", "parse_input", "render_output"]
