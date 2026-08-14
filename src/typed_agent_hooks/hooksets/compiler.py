"""Compile declarative hooksets into provider-native typed configuration."""

import shlex
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, TypeAlias, cast

from typed_agent_hooks import claude_code, codex
from typed_agent_hooks.loader import split_object_spec

from .launcher import default_command_prefix
from .mapping import SHARED_TO_CLAUDE_CODE, SHARED_TO_CODEX
from .models import (
    ClaudeCodeHookSet,
    CodexHookSet,
    FastmcpHookSet,
    HookSet,
    ProviderName,
    SharedHookSet,
)

CompiledConfig: TypeAlias = codex.config.HooksFile | claude_code.config.SettingsHooks
ProviderSelection: TypeAlias = ProviderName | Literal["all"]


def target_providers(
    hookset: HookSet, requested: ProviderSelection = "all"
) -> tuple[ProviderName, ...]:
    """Resolve the providers allowed by a hookset and CLI selection."""

    if isinstance(hookset, CodexHookSet):
        allowed: tuple[ProviderName, ...] = ("codex",)
    elif isinstance(hookset, ClaudeCodeHookSet):
        allowed = ("claude_code",)
    elif isinstance(hookset, FastmcpHookSet):
        allowed = (hookset.provider,)
    else:
        allowed = tuple(hookset.providers)

    if requested == "all":
        return allowed
    if requested not in allowed:
        raise ValueError(f"hookset mode {hookset.mode!r} cannot target provider {requested!r}")
    return (requested,)


def resolve_app_spec(app: str, *, base_dir: str | Path) -> str:
    """Resolve a file-based app spec relative to its hookset file."""

    target, object_name = split_object_spec(app)
    is_path = target.endswith(".py") or "/" in target or "\\" in target
    if not is_path:
        return app
    path = Path(target).expanduser()
    if not path.is_absolute():
        path = Path(base_dir).expanduser() / path
    return f"{path.resolve()}:{object_name}"


def _runner_args(
    mode: str,
    provider: ProviderName,
    app_spec: str,
    hookset_name: str,
) -> list[str]:
    cli_mode = mode.replace("_", "-")
    args = [cli_mode, app_spec]
    if mode == "shared":
        args.extend(["--provider", provider.replace("_", "-")])
    args.extend(["--hookset-name", hookset_name])
    return args


def _forward_args(provider: ProviderName, server: str, hookset_name: str) -> list[str]:
    return [
        "--provider",
        provider.replace("_", "-"),
        "--server-name",
        server,
        "--hookset-name",
        hookset_name,
    ]


def _codex_command(
    *,
    command_prefix: Sequence[str],
    mode: str,
    app_spec: str,
    hookset_name: str,
) -> str:
    args = _runner_args(mode, "codex", app_spec, hookset_name)
    return shlex.join([*command_prefix, *args])


def _claude_command(
    *,
    command_prefix: Sequence[str],
    mode: str,
    app_spec: str,
    hookset_name: str,
) -> tuple[str, list[str]]:
    args = _runner_args(mode, "claude_code", app_spec, hookset_name)
    return command_prefix[0], [*command_prefix[1:], *args]


def _compile_codex(
    hookset: CodexHookSet | SharedHookSet,
    *,
    app_spec: str,
    command_prefix: Sequence[str],
) -> codex.config.HooksFile:
    command = _codex_command(
        command_prefix=command_prefix,
        mode=hookset.mode,
        app_spec=app_spec,
        hookset_name=hookset.name,
    )
    hooks: dict[codex.events.CodexEventName, list[codex.config.HookGroup]] = {}

    if isinstance(hookset, CodexHookSet):
        for codex_spec in hookset.hooks:
            handler = codex.config.CommandHook(
                command=command,
                timeout=codex_spec.timeout,
                status_message=codex_spec.status_message,
                command_windows=codex_spec.command_windows,
            )
            group = codex.config.HookGroup(matcher=codex_spec.matcher, hooks=[handler])
            hooks.setdefault(codex_spec.event, []).append(group)
    else:
        for shared_spec in hookset.hooks:
            options = shared_spec.codex
            mapped = SHARED_TO_CODEX.get(shared_spec.event)
            if mapped is None:
                # E.g. ToolCallFailed: Claude Code-only. Loud beats a KeyError
                # and beats silently thinning the hookset for one provider.
                raise ValueError(
                    f"shared event {shared_spec.event!r} has no Codex equivalent; "
                    "use a provider-specific hookset for it"
                )
            event = mapped
            handler = codex.config.CommandHook(
                command=command,
                timeout=(options.timeout if options.timeout is not None else shared_spec.timeout),
                status_message=(
                    options.status_message
                    if options.status_message is not None
                    else shared_spec.status_message
                ),
                command_windows=options.command_windows,
            )
            group = codex.config.HookGroup(matcher=options.matcher, hooks=[handler])
            hooks.setdefault(event, []).append(group)

    return codex.config.HooksFile(hooks=hooks)


def _compile_claude_code(
    hookset: ClaudeCodeHookSet | SharedHookSet,
    *,
    app_spec: str,
    command_prefix: Sequence[str],
) -> claude_code.config.SettingsHooks:
    command, args = _claude_command(
        command_prefix=command_prefix,
        mode=hookset.mode,
        app_spec=app_spec,
        hookset_name=hookset.name,
    )
    hooks: dict[claude_code.events.ClaudeEventName, list[claude_code.config.HookGroup]] = {}

    if isinstance(hookset, ClaudeCodeHookSet):
        for claude_spec in hookset.hooks:
            handler = claude_code.config.CommandHook(
                command=command,
                args=args,
                timeout=claude_spec.timeout,
                status_message=claude_spec.status_message,
                condition=claude_spec.condition,
                async_=claude_spec.async_,
                async_rewake=claude_spec.async_rewake,
                shell=claude_spec.shell,
            )
            group = claude_code.config.HookGroup(matcher=claude_spec.matcher, hooks=[handler])
            hooks.setdefault(claude_spec.event, []).append(group)
    else:
        for shared_spec in hookset.hooks:
            options = shared_spec.claude_code
            event = SHARED_TO_CLAUDE_CODE[shared_spec.event]
            handler = claude_code.config.CommandHook(
                command=command,
                args=args,
                timeout=(options.timeout if options.timeout is not None else shared_spec.timeout),
                status_message=(
                    options.status_message
                    if options.status_message is not None
                    else shared_spec.status_message
                ),
                condition=options.condition,
                async_=options.async_,
                async_rewake=options.async_rewake,
                shell=options.shell,
            )
            group = claude_code.config.HookGroup(matcher=options.matcher, hooks=[handler])
            hooks.setdefault(event, []).append(group)

    return claude_code.config.SettingsHooks(hooks=hooks)


def _compile_fastmcp(
    hookset: FastmcpHookSet,
    *,
    provider: ProviderName,
    command_prefix: Sequence[str],
) -> CompiledConfig:
    fwd = _forward_args(provider, hookset.server, hookset.name)
    if provider == "codex":
        command = shlex.join([*command_prefix, *fwd])
        codex_hooks: dict[codex.events.CodexEventName, list[codex.config.HookGroup]] = {}
        for spec in hookset.hooks:
            handler = codex.config.CommandHook(
                command=command,
                timeout=spec.timeout,
                status_message=spec.status_message,
                command_windows=spec.command_windows,
            )
            group = codex.config.HookGroup(matcher=spec.matcher, hooks=[handler])
            codex_hooks.setdefault(cast(codex.events.CodexEventName, spec.event), []).append(group)
        return codex.config.HooksFile(hooks=codex_hooks)

    exe, exe_args = command_prefix[0], [*command_prefix[1:], *fwd]
    claude_hooks: dict[claude_code.events.ClaudeEventName, list[claude_code.config.HookGroup]] = {}
    for spec in hookset.hooks:
        handler = claude_code.config.CommandHook(
            command=exe,
            args=exe_args,
            timeout=spec.timeout,
            status_message=spec.status_message,
            condition=spec.condition,
            async_=spec.async_,
            async_rewake=spec.async_rewake,
            shell=spec.shell,
        )
        group = claude_code.config.HookGroup(matcher=spec.matcher, hooks=[handler])
        claude_hooks.setdefault(cast(claude_code.events.ClaudeEventName, spec.event), []).append(
            group
        )
    return claude_code.config.SettingsHooks(hooks=claude_hooks)


def compile_hookset(
    hookset: HookSet,
    *,
    provider: ProviderName,
    base_dir: str | Path = ".",
    python_executable: str | None = None,
    command_prefix: Sequence[str] | None = None,
) -> CompiledConfig:
    """Compile one hookset for one explicit provider.

    ``command_prefix`` is the complete executable prefix before hook-specific
    arguments. When omitted, an explicit ``python_executable`` is honored;
    otherwise Git installations self-bootstrap through uvx so generated config
    never points into an ephemeral installer environment.
    """

    target_providers(hookset, provider)
    executable = python_executable or sys.executable
    prefix = (
        list(command_prefix)
        if command_prefix is not None
        else default_command_prefix(
            hookset.mode,
            python_executable=executable,
            self_bootstrap=python_executable is None,
        )
    )
    if not prefix:
        raise ValueError("command_prefix must contain at least one argument")
    if isinstance(hookset, FastmcpHookSet):
        return _compile_fastmcp(
            hookset,
            provider=provider,
            command_prefix=prefix,
        )
    app_spec = resolve_app_spec(hookset.app, base_dir=base_dir)

    if provider == "codex":
        if isinstance(hookset, ClaudeCodeHookSet):
            raise AssertionError("provider compatibility check failed")
        return _compile_codex(hookset, app_spec=app_spec, command_prefix=prefix)
    if isinstance(hookset, CodexHookSet):
        raise AssertionError("provider compatibility check failed")
    return _compile_claude_code(hookset, app_spec=app_spec, command_prefix=prefix)


def compile_hooksets(
    hookset: HookSet,
    *,
    provider: ProviderSelection = "all",
    base_dir: str | Path = ".",
    python_executable: str | None = None,
    command_prefix: Sequence[str] | None = None,
) -> dict[ProviderName, CompiledConfig]:
    """Compile a hookset for every selected provider."""

    return {
        target: compile_hookset(
            hookset,
            provider=target,
            base_dir=base_dir,
            python_executable=python_executable,
            command_prefix=command_prefix,
        )
        for target in target_providers(hookset, provider)
    }
