"""Explicit shared semantic hook application."""

from collections.abc import Callable, Mapping
from typing import TypeVar

from typed_agent_hooks import claude_code, codex
from typed_agent_hooks.core import JsonInput, Provider
from typed_agent_hooks.registry import ErasedHandler, Handler, HandlerRegistry

from .adapters import from_claude_code, from_codex
from .events import EVENT_NAME_BY_TYPE, BaseEvent, SharedEventName
from .outputs import Result, to_claude_code_output, to_codex_output

EventT = TypeVar("EventT", bound=BaseEvent)


class HookApp:
    """Map provider wire events into shared events before typed dispatch."""

    def __init__(self) -> None:
        self._registry: HandlerRegistry[BaseEvent, SharedEventName, Result] = HandlerRegistry(
            EVENT_NAME_BY_TYPE
        )

    def on(
        self, event_type: type[EventT]
    ) -> Callable[[Handler[EventT, Result]], Handler[EventT, Result]]:
        """Register a handler for one concrete shared semantic event model."""

        return self._registry.on(event_type)

    @property
    def handlers(self) -> Mapping[SharedEventName, ErasedHandler[BaseEvent, Result]]:
        """Read-only registered handler mapping."""

        return self._registry.handlers

    def handle_codex_event(self, wire_event: codex.events.AnyInput) -> str | None:
        """Map, dispatch, and render one Codex event through shared mode."""

        event = from_codex(wire_event)
        result = self._registry.call(event.event_name, event)
        output = to_codex_output(event, result)
        return codex.render_output(wire_event.hook_event_name, output)

    def handle_claude_code_event(self, wire_event: claude_code.events.AnyInput) -> str | None:
        """Map, dispatch, and render one Claude Code event through shared mode."""

        event = from_claude_code(wire_event)
        result = self._registry.call(event.event_name, event)
        output = to_claude_code_output(event, result)
        return claude_code.render_output(wire_event.hook_event_name, output)

    def handle_json(self, provider: Provider, data: JsonInput) -> str | None:
        """Parse and handle one provider payload in shared mode."""

        if provider is Provider.CODEX:
            return self.handle_codex_event(codex.parse_input(data))
        return self.handle_claude_code_event(claude_code.parse_input(data))
