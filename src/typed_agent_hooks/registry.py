"""Typed handler registration shared by provider-specific applications."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Generic, TypeVar, cast

BaseEventT = TypeVar("BaseEventT")
SpecificEventT = TypeVar("SpecificEventT")
EventNameT = TypeVar("EventNameT", bound=str)
ResultT = TypeVar("ResultT")
Handler = Callable[[SpecificEventT], ResultT]
ErasedHandler = Callable[[BaseEventT], ResultT]


class HandlerRegistry(Generic[BaseEventT, EventNameT, ResultT]):
    """Register one synchronous handler per concrete event model."""

    def __init__(self, event_names: Mapping[type[BaseEventT], EventNameT]) -> None:
        self._event_names = dict(event_names)
        self._handlers: dict[EventNameT, ErasedHandler[BaseEventT, ResultT]] = {}

    def on(
        self,
        event_type: type[SpecificEventT],
    ) -> Callable[[Handler[SpecificEventT, ResultT]], Handler[SpecificEventT, ResultT]]:
        """Return a decorator for one concrete event model."""

        base_event_type = cast(type[BaseEventT], event_type)
        try:
            event_name = self._event_names[base_event_type]
        except KeyError as exc:
            raise ValueError(f"unsupported event model {event_type.__name__}") from exc
        if event_name in self._handlers:
            raise ValueError(f"handler already registered for {event_name}")

        def register(
            handler: Handler[SpecificEventT, ResultT],
        ) -> Handler[SpecificEventT, ResultT]:
            def erased(event: BaseEventT) -> ResultT:
                if not isinstance(event, event_type):
                    raise AssertionError(
                        f"registry routed {type(event).__name__} to {event_type.__name__} handler"
                    )
                result = handler(event)
                if inspect.isawaitable(result):
                    raise TypeError("async hook handlers are not supported by the command runner")
                return result

            self._handlers[event_name] = erased
            return handler

        return register

    @property
    def handlers(self) -> Mapping[EventNameT, ErasedHandler[BaseEventT, ResultT]]:
        """Read-only registered handler mapping keyed by wire/semantic event name."""

        return MappingProxyType(self._handlers)

    def call(self, event_name: EventNameT, event: BaseEventT) -> ResultT | None:
        """Invoke a handler when registered; otherwise return ``None``."""

        handler = self._handlers.get(event_name)
        return None if handler is None else handler(event)
