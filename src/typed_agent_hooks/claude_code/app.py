"""Claude Code-specific synchronous hook application."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TypeVar

from typed_agent_hooks.core import JsonInput
from typed_agent_hooks.registry import ErasedHandler, Handler, HandlerRegistry

from .events import (
    EVENT_NAME_BY_TYPE,
    AnyInput,
    BaseInput,
    ClaudeEventName,
    parse_input,
)
from .outputs import HookResult, render_output

EventT = TypeVar("EventT", bound=BaseInput)


class HookApp:
    """Dispatch strict Claude Code wire events to registered handlers."""

    def __init__(self) -> None:
        self._registry: HandlerRegistry[BaseInput, ClaudeEventName, HookResult] = HandlerRegistry(
            EVENT_NAME_BY_TYPE
        )

    def on(
        self, event_type: type[EventT]
    ) -> Callable[[Handler[EventT, HookResult]], Handler[EventT, HookResult]]:
        """Register a handler for one concrete Claude Code event model."""

        return self._registry.on(event_type)

    @property
    def handlers(self) -> Mapping[ClaudeEventName, ErasedHandler[BaseInput, HookResult]]:
        """Read-only registered handler mapping."""

        return self._registry.handlers

    def handle_event(self, event: AnyInput) -> str | None:
        """Dispatch and render one already parsed Claude Code event."""

        result = self._registry.call(event.hook_event_name, event)
        return render_output(event.hook_event_name, result)

    def handle_json(self, data: JsonInput) -> str | None:
        """Parse, dispatch, and render one Claude Code command-hook payload."""

        return self.handle_event(parse_input(data))
