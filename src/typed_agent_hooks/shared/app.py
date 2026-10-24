"""Run one hook file: dispatch a host payload to a typed shared-event handler."""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar, cast

from typed_agent_hooks.core import HOSTS, Host, JsonInput

from .adapters import from_claude_code, from_codex
from .events import EVENT_TYPES, AnyEvent, BaseEvent
from .outputs import Result, to_claude_code_output, to_codex_output

EventT = TypeVar("EventT", bound=BaseEvent)
Handler = Callable[[EventT], Result]


class HookApp:
    """The handlers of one hook file, keyed by shared event type.

    The host files (`.codex/hooks.json`, `.claude/settings.json`) hold the
    native event, matcher, timeout and command. The command runs the hook
    file with the host name as its only argument and the payload on stdin.
    """

    def __init__(self, *, name: str) -> None:
        self.name = name
        self.handlers: dict[type[BaseEvent], Callable[[Any], Result]] = {}

    def on(self, event_type: type[EventT]) -> Callable[[Handler[EventT]], Handler[EventT]]:
        """Register the decorated function as the handler of one shared event type."""

        if event_type not in EVENT_TYPES:
            raise ValueError(f"unsupported event model {event_type.__name__}")

        def register(handler: Handler[EventT]) -> Handler[EventT]:
            if event_type in self.handlers:
                raise ValueError(f"handler already registered for {event_type.__name__}")
            self.handlers[event_type] = handler
            return handler

        return register

    def handle(self, host: Host, payload: JsonInput) -> str | None:
        """Parse one host payload, call its handler, and render the host output.

        Returns ``None`` when the handler returns ``None``. Raises on every
        failure, including an event that has no handler.
        """

        if host == "codex":
            from typed_agent_hooks import codex

            codex_event = codex.parse_input(payload)
            event = from_codex(codex_event)
            output = to_codex_output(event, self._call(event))
            return codex.render_output(codex_event.hook_event_name, output)
        if host == "claude":
            from typed_agent_hooks import claude_code

            claude_event = claude_code.parse_input(payload)
            event = from_claude_code(claude_event)
            output = to_claude_code_output(event, self._call(event))
            return claude_code.render_output(claude_event.hook_event_name, output)
        raise ValueError(f"unknown host {host!r}")

    def _call(self, event: AnyEvent) -> Result:
        handler = self.handlers.get(type(event))
        if handler is None:
            raise LookupError(f"no handler for {event.context.host} {event.context.source_event}")
        return handler(event)

    def main(self) -> None:
        """Run as a hook command: ``HOOK_FILE codex|claude`` with the payload on stdin.

        Writes the host output, if any, to stdout. What a handler prints goes
        to stderr. Any failure after the host argument is read (a bad payload,
        an event with no handler, a handler exception or ``sys.exit``, an
        output the event cannot carry) fails open: one line on stderr, nothing
        on stdout, exit 0. A missing or unknown host argument is a programming
        error: a usage line on stderr and exit 1, which both hosts treat as a
        non-blocking error.
        """

        args = sys.argv[1:]
        if len(args) != 1 or args[0] not in HOSTS:
            hosts = "|".join(HOSTS)
            print(f"usage: {Path(sys.argv[0]).name} {hosts} < payload.json", file=sys.stderr)
            raise SystemExit(1)
        host = cast(Host, args[0])
        try:
            # Both hosts read stdout as the hook output, so a handler's print
            # must not reach it.
            with contextlib.redirect_stdout(sys.stderr):
                output = self.handle(host, sys.stdin.buffer.read())
            if output is not None:
                # Both hosts read hook stdout as UTF-8, whatever the locale.
                sys.stdout.buffer.write(output.encode() + b"\n")
        # A handler's exit code must not reach the host: exit 2 blocks the action.
        except (Exception, SystemExit) as error:
            detail = " ".join(str(error).split())
            print(f"{self.name}: {type(error).__name__}: {detail}", file=sys.stderr)
