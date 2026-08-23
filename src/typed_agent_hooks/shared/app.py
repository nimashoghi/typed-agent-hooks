"""Code-first shared semantic hook application."""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeVar, cast

from typed_agent_hooks import claude_code, codex
from typed_agent_hooks.config import (
    ALL_PROVIDERS,
    ConfigChange,
    ProviderName,
    ProviderSelection,
    Scope,
    config_dict,
    reconcile_app_configs,
    validate_name,
)
from typed_agent_hooks.core import JsonInput, Provider
from typed_agent_hooks.internal import APP_MARKER, COLLECTION_MARKER, INTERNAL_COMMAND
from typed_agent_hooks.protocol import AppDescription
from typed_agent_hooks.registry import ErasedHandler, Handler, HandlerRegistry

from .adapters import from_claude_code, from_codex
from .config import SHARED_TO_CLAUDE_CODE, SHARED_TO_CODEX, ClaudeCodeOptions, CodexOptions
from .events import EVENT_NAME_BY_TYPE, BaseEvent, SharedEventName
from .outputs import Result, to_claude_code_output, to_codex_output

EventT = TypeVar("EventT", bound=BaseEvent)


class CommandLine(Protocol):
    """Callable fallback for a domain CLI such as a Cyclopts application."""

    def __call__(self) -> object: ...


@dataclass(frozen=True, slots=True)
class Registration:
    """One handler and its provider command-hook metadata."""

    event_type: type[BaseEvent]
    event_name: SharedEventName
    timeout: int | None
    status_message: str | None
    codex: CodexOptions
    claude_code: ClaudeCodeOptions


def _provider_name(provider: Provider) -> ProviderName:
    return provider.value


def _provider_enum(provider: ProviderName) -> Provider:
    return Provider(provider)


def _enabled_providers(values: Iterable[ProviderName]) -> tuple[ProviderName, ...]:
    raw = tuple(values)
    if not raw:
        raise ValueError("providers must contain at least one provider")
    if len(set(raw)) != len(raw):
        raise ValueError("providers must not contain duplicates")
    unknown = set(raw) - set(ALL_PROVIDERS)
    if unknown:
        raise ValueError(f"unsupported providers: {', '.join(sorted(unknown))}")
    return tuple(provider for provider in ALL_PROVIDERS if provider in raw)


def _runtime_tokens(
    executable: Path,
    *,
    provider: ProviderName,
    app_name: str,
    collection_name: str | None,
) -> list[str]:
    tokens = [
        str(executable),
        INTERNAL_COMMAND,
        "run",
        "--provider",
        provider,
        APP_MARKER,
        app_name,
    ]
    if collection_name is not None:
        tokens.extend([COLLECTION_MARKER, collection_name])
    return tokens


class HookApp:
    """Define and execute one named provider-independent hook application."""

    def __init__(
        self,
        *,
        name: str,
        providers: Iterable[ProviderName] = ALL_PROVIDERS,
    ) -> None:
        self.name = validate_name(name, kind="app name")
        self.providers = _enabled_providers(providers)
        self._registry: HandlerRegistry[BaseEvent, SharedEventName, Result] = HandlerRegistry(
            EVENT_NAME_BY_TYPE
        )
        self._registrations: dict[SharedEventName, Registration] = {}

    def on(
        self,
        event_type: type[EventT],
        *,
        timeout: int | None = None,
        status_message: str | None = None,
        codex: CodexOptions | None = None,
        claude_code: ClaudeCodeOptions | None = None,
    ) -> Callable[[Handler[EventT, Result]], Handler[EventT, Result]]:
        """Register one handler together with its provider hook configuration."""

        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be positive")
        codex_options = codex or CodexOptions()
        claude_options = claude_code or ClaudeCodeOptions()
        if "codex" not in self.providers and codex_options.model_dump(exclude_none=True):
            raise ValueError("Codex options require the app to enable Codex")
        if "claude_code" not in self.providers and claude_options.model_dump(exclude_none=True):
            raise ValueError("Claude Code options require the app to enable Claude Code")

        try:
            event_name = EVENT_NAME_BY_TYPE[cast(type[BaseEvent], event_type)]
        except KeyError as exc:
            raise ValueError(f"unsupported event model {event_type.__name__}") from exc
        register = self._registry.on(event_type)

        def decorator(handler: Handler[EventT, Result]) -> Handler[EventT, Result]:
            registered = register(handler)
            self._registrations[event_name] = Registration(
                event_type=cast(type[BaseEvent], event_type),
                event_name=event_name,
                timeout=timeout,
                status_message=status_message,
                codex=codex_options,
                claude_code=claude_options,
            )
            return registered

        return decorator

    @property
    def handlers(self) -> Mapping[SharedEventName, ErasedHandler[BaseEvent, Result]]:
        """Read-only registered handler mapping."""

        return self._registry.handlers

    @property
    def registrations(self) -> tuple[Registration, ...]:
        """Registered events and provider configuration in definition order."""

        return tuple(self._registrations.values())

    def handle_codex_event(self, wire_event: codex.events.AnyInput) -> str | None:
        """Map, dispatch, and render one Codex event."""

        event = from_codex(wire_event)
        result = self._registry.call(event.event_name, event)
        return codex.render_output(
            wire_event.hook_event_name,
            to_codex_output(event, result),
        )

    def handle_claude_code_event(self, wire_event: claude_code.events.AnyInput) -> str | None:
        """Map, dispatch, and render one Claude Code event."""

        event = from_claude_code(wire_event)
        result = self._registry.call(event.event_name, event)
        return claude_code.render_output(
            wire_event.hook_event_name,
            to_claude_code_output(event, result),
        )

    def handle_json(self, provider: Provider, data: JsonInput) -> str | None:
        """Parse and handle one provider payload."""

        provider_name = _provider_name(provider)
        if provider_name not in self.providers:
            raise ValueError(f"app {self.name!r} does not enable {provider_name}")
        if provider is Provider.CODEX:
            return self.handle_codex_event(codex.parse_input(data))
        return self.handle_claude_code_event(claude_code.parse_input(data))

    def render(
        self,
        provider: ProviderName,
        *,
        executable: str | Path,
        collection: str | None = None,
    ) -> dict[str, object]:
        """Render this application's provider-native command-hook configuration."""

        if provider not in self.providers:
            raise ValueError(f"app {self.name!r} does not enable {provider}")
        if collection is not None:
            validate_name(collection, kind="collection name")
        path = Path(executable).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if not os.access(path, os.X_OK):
            raise PermissionError(f"hook executable is not executable: {path}")
        tokens = _runtime_tokens(
            path,
            provider=provider,
            app_name=self.name,
            collection_name=collection,
        )

        if provider == "codex":
            hooks: dict[codex.events.CodexEventName, list[codex.config.HookGroup]] = {}
            for registration in self.registrations:
                event = SHARED_TO_CODEX.get(registration.event_name)
                if event is None:
                    raise ValueError(
                        f"shared event {registration.event_name!r} has no Codex equivalent"
                    )
                options = registration.codex
                command = codex.config.CommandHook(
                    command=shlex.join(tokens),
                    timeout=(
                        options.timeout if options.timeout is not None else registration.timeout
                    ),
                    status_message=(
                        options.status_message
                        if options.status_message is not None
                        else registration.status_message
                    ),
                    command_windows=options.command_windows,
                )
                hooks.setdefault(event, []).append(
                    codex.config.HookGroup(matcher=options.matcher, hooks=[command])
                )
            return config_dict(codex.config.HooksFile(hooks=hooks))

        claude_hooks: dict[
            claude_code.events.ClaudeEventName, list[claude_code.config.HookGroup]
        ] = {}
        for registration in self.registrations:
            event = SHARED_TO_CLAUDE_CODE[registration.event_name]
            options = registration.claude_code
            command = claude_code.config.CommandHook(
                command=tokens[0],
                args=tokens[1:],
                timeout=(options.timeout if options.timeout is not None else registration.timeout),
                status_message=(
                    options.status_message
                    if options.status_message is not None
                    else registration.status_message
                ),
                condition=options.condition,
                async_=options.async_,
                async_rewake=options.async_rewake,
                shell=options.shell,
            )
            claude_hooks.setdefault(event, []).append(
                claude_code.config.HookGroup(matcher=options.matcher, hooks=[command])
            )
        return config_dict(claude_code.config.SettingsHooks(hooks=claude_hooks))

    def describe(
        self,
        *,
        executable: str | Path,
        collection: str | None = None,
    ) -> AppDescription:
        """Describe every enabled provider for collection reconciliation."""

        return AppDescription(
            name=self.name,
            providers=self.providers,
            configs={
                provider: self.render(provider, executable=executable, collection=collection)
                for provider in self.providers
            },
        )

    def install(
        self,
        *,
        executable: str | Path,
        provider: ProviderSelection = "all",
        scope: Scope = "project",
        project_root: str | Path = ".",
        target_path: str | Path | None = None,
    ) -> dict[ProviderName, ConfigChange]:
        """Reconcile this application across selected provider configs."""

        generated = {
            enabled: self.render(enabled, executable=executable) for enabled in self.providers
        }
        return reconcile_app_configs(
            self.name,
            generated,
            provider=provider,
            scope=scope,
            project_root=project_root,
            target_path=target_path,
        )

    def uninstall(
        self,
        *,
        provider: ProviderSelection = "all",
        scope: Scope = "project",
        project_root: str | Path = ".",
        target_path: str | Path | None = None,
    ) -> dict[ProviderName, ConfigChange]:
        """Remove this application from selected provider configs."""

        return reconcile_app_configs(
            self.name,
            {},
            provider=provider,
            scope=scope,
            project_root=project_root,
            target_path=target_path,
        )

    def main(self, cli: CommandLine | None = None) -> object:
        """Run the private hook protocol or delegate unchanged to a domain CLI."""

        args = sys.argv[1:]
        if not args or args[0] != INTERNAL_COMMAND:
            if cli is None:
                raise SystemExit(f"expected {INTERNAL_COMMAND}")
            return cli()
        raise SystemExit(self._internal_main(args[1:], executable=Path(sys.argv[0])))

    def _internal_main(self, args: list[str], *, executable: Path) -> int:
        parser = argparse.ArgumentParser(prog=f"{executable.name} {INTERNAL_COMMAND}")
        commands = parser.add_subparsers(dest="command", required=True)

        run = commands.add_parser("run")
        run.add_argument("--provider", choices=ALL_PROVIDERS, required=True)
        run.add_argument(APP_MARKER, required=True)
        run.add_argument(COLLECTION_MARKER)

        describe = commands.add_parser("describe")
        describe.add_argument(COLLECTION_MARKER)

        install = commands.add_parser("install")
        self._add_location_arguments(install)

        uninstall = commands.add_parser("uninstall")
        self._add_location_arguments(uninstall)

        parsed = parser.parse_args(args)
        if parsed.command == "run":
            if parsed.managed_app != self.name:
                raise ValueError(
                    f"managed app marker {parsed.managed_app!r} does not match {self.name!r}"
                )
            payload = sys.stdin.read()
            if not payload.strip():
                raise ValueError("expected hook JSON on stdin")
            output = self.handle_json(_provider_enum(parsed.provider), payload)
            if output is not None:
                print(output)
            return 0
        if parsed.command == "describe":
            print(
                self.describe(
                    executable=executable,
                    collection=parsed.managed_collection,
                ).model_dump_json()
            )
            return 0
        if parsed.command == "install":
            changes = self.install(
                executable=executable,
                provider=parsed.provider,
                scope=parsed.scope,
                project_root=parsed.project_root,
                target_path=parsed.path,
            )
        else:
            changes = self.uninstall(
                provider=parsed.provider,
                scope=parsed.scope,
                project_root=parsed.project_root,
                target_path=parsed.path,
            )
        for provider, change in changes.items():
            status = "updated" if change.changed else "unchanged"
            print(f"{provider}: {status} {change.path}")
        return 0

    @staticmethod
    def _add_location_arguments(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--provider", choices=(*ALL_PROVIDERS, "all"), default="all")
        parser.add_argument("--scope", choices=("project", "user"), default="project")
        parser.add_argument("--project-root", default=".")
        parser.add_argument("--path")
