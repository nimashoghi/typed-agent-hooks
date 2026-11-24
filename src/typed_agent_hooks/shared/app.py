"""Run one hook file: dispatch a host payload to a typed shared-event handler."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar, cast

from typed_agent_hooks import agy, claude_code, codex
from typed_agent_hooks.core import HOSTS, Host, JsonInput, render_json

from .adapters import from_agy, from_claude_code, from_codex
from .agy_outputs import to_agy_output
from .claude_code_outputs import to_claude_code_output
from .codex_outputs import to_codex_output
from .events import EVENT_TYPES, AnyEvent, BaseEvent, ToolCallCompleted, ToolCallFailed
from .outputs import Result

EventT = TypeVar("EventT", bound=BaseEvent)
Handler = Callable[[EventT], Result]


class HookApp:
    """The handlers of one hook file, keyed by shared event type.

    The host files (`.codex/hooks.json`, `.claude/settings.json`,
    `.agents/hooks.json`) hold the native event, matcher, timeout and command.
    The command runs the hook file with the host name as its only argument and
    the payload on stdin.
    """

    def __init__(self, *, name: str) -> None:
        self.name = name
        self.handlers: dict[type[BaseEvent], Callable[[Any], Result]] = {}
        # After handle(): a note for each field of the result that the host left
        # out (agy has no informational system_message). main() writes no notes:
        # nothing reads a hook's stderr reliably, and a write there could delay
        # the exit that the host waits for.
        self.notes: list[str] = []

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

        Afterwards, ``notes`` lists the fields of the result that the host
        left out. Returns ``None`` when the handler returns ``None``. In agy, it also
        returns ``None`` without a handler for a PreInvocation that does not
        answer a user prompt, and for a PostToolUse that a hook does not handle
        but whose other kind (completed or failed call) it handles. Raises on
        every other failure, including an event that has no handler.
        """

        notes: list[str] = []
        try:
            output, notes = self._dispatch(host, payload)
            return output
        finally:
            # Also after a failure (with no notes), and after any call that the
            # handler made on this app meanwhile.
            self.notes = notes

    def _dispatch(self, host: Host, payload: JsonInput) -> tuple[str | None, list[str]]:
        """handle()'s work, with a note for each field of the result that the
        host leaves out. A note exists only for an output that rendered."""

        notes: list[str] = []
        if host == "codex":
            event = from_codex(codex.parse_input(payload))
            output = to_codex_output(event, self._call(event))
        elif host == "claude":
            event = from_claude_code(claude_code.parse_input(payload))
            output = to_claude_code_output(event, self._call(event))
        elif host == "agy":
            if (agy_event := from_agy(agy.parse_input(payload))) is None:
                return None, []
            # agy sends completed and failed tool calls as one event, PostToolUse.
            # A hook registered there for one kind also gets the other.
            tool_events = {ToolCallCompleted, ToolCallFailed}
            if type(agy_event) in tool_events - self.handlers.keys() and (
                tool_events & self.handlers.keys()
            ):
                return None, []
            # The handler gets a copy, so that a handler that changes tool_input
            # cannot hide from the converter the arguments that agy sent.
            result = self._call(agy_event.model_copy(deep=True))
            output, notes = to_agy_output(agy_event, result)
        else:
            raise ValueError(f"unknown host {host!r}")
        if output is None:
            return None, []
        return render_json(output), notes

    def _call(self, event: AnyEvent) -> Result:
        handler = self.handlers.get(type(event))
        if handler is None:
            raise LookupError(f"no handler for {event.context.host} {event.context.source_event}")
        return handler(event)

    def main(self) -> None:
        """Run as a hook command: ``HOOK_FILE codex|claude|agy`` with the payload on stdin.

        Writes the host output, if any, to stdout. Everything else that the
        process writes to stdout (a print at import or in a handler, a child
        process, a C library) goes to stderr. Text that was already flushed to
        stdout before ``main()`` (``python -u``, ``PYTHONUNBUFFERED`` or an
        explicit flush) cannot be recalled. Any failure after the host argument is read (a
        bad payload, an event with no handler, a handler exception or
        ``sys.exit``, an output the event cannot carry) fails open: one line on
        stderr, nothing on stdout, exit 0. A missing or unknown host argument
        is a programming error: a usage line on stderr and exit 1, which the
        hosts treat as a non-blocking error.
        """

        args = sys.argv[1:]
        if len(args) != 1 or args[0] not in HOSTS:
            hosts = "|".join(HOSTS)
            print(f"usage: {Path(sys.argv[0]).name} {hosts} < payload.json", file=sys.stderr)
            raise SystemExit(1)
        host = cast(Host, args[0])
        try:
            # The hosts read stdout as the hook output. Keep a private copy of
            # it, and point descriptor 1 at stderr until the process exits. Do
            # not flush first: text that is still in the stdout buffer, such as
            # a print at import, then goes to stderr.
            with os.fdopen(os.dup(1), "wb") as host_stdout:
                os.dup2(2, 1)
                output = self.handle(host, sys.stdin.buffer.read())
                if output is not None:
                    # The hosts read hook stdout as UTF-8, whatever the locale.
                    host_stdout.write(output.encode() + b"\n")
                    host_stdout.flush()
        # A handler's exit code must not reach the host: exit 2 blocks the action.
        except (Exception, SystemExit) as error:
            detail = " ".join(str(error).split())
            print(f"{self.name}: {type(error).__name__}: {detail}", file=sys.stderr)
