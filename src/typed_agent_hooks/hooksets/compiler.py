"""Compile declarative hooksets into provider-native typed configuration."""

import shlex
import sys
from pathlib import Path
from typing import Literal, TypeAlias

from typed_agent_hooks import claude_code, codex

from .mapping import SHARED_TO_CLAUDE_CODE, SHARED_TO_CODEX
from .models import (
    ClaudeCodeHookSet,
    CodexHookSet,
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
    else:
        allowed = tuple(hookset.providers)

    if requested == "all":
        return allowed
    if requested not in allowed:
        raise ValueError(f"hookset mode {hookset.mode!r} cannot target provider {requested!r}")
    return (requested,)


def resolve_app_spec(app: str, *, base_dir: str | Path) -> str:
    """Resolve a file-based app spec relative to its hookset file."""

    target, object_name = app.split(":", 1)
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
    args = ["-m", "typed_agent_hooks", "run", cli_mode, app_spec]
    if mode == "shared":
        args.extend(["--provider", provider.replace("_", "-")])
    args.extend(["--hookset-name", hookset_name])
    return args


def _codex_command(
    *,
    python_executable: str,
    mode: str,
    app_spec: str,
    hookset_name: str,
) -> str:
    args = _runner_args(mode, "codex", app_spec, hookset_name)
    return shlex.join([python_executable, *args])


def _claude_command(
    *,
    python_executable: str,
    mode: str,
    app_spec: str,
    hookset_name: str,
) -> tuple[str, list[str]]:
    args = _runner_args(mode, "claude_code", app_spec, hookset_name)
    return python_executable, args


def _compile_codex(
    hookset: CodexHookSet | SharedHookSet,
    *,
    app_spec: str,
    python_executable: str,
) -> codex.config.HooksFile:
    command = _codex_command(
        python_executable=python_executable,
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
            event = SHARED_TO_CODEX[shared_spec.event]
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
    python_executable: str,
) -> claude_code.config.SettingsHooks:
    command, args = _claude_command(
        python_executable=python_executable,
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


def compile_hookset(
    hookset: HookSet,
    *,
    provider: ProviderName,
    base_dir: str | Path = ".",
    python_executable: str | None = None,
) -> CompiledConfig:
    """Compile one hookset for one explicit provider."""

    target_providers(hookset, provider)
    executable = python_executable or sys.executable
    app_spec = resolve_app_spec(hookset.app, base_dir=base_dir)

    if provider == "codex":
        if isinstance(hookset, ClaudeCodeHookSet):
            raise AssertionError("provider compatibility check failed")
        return _compile_codex(hookset, app_spec=app_spec, python_executable=executable)
    if isinstance(hookset, CodexHookSet):
        raise AssertionError("provider compatibility check failed")
    return _compile_claude_code(hookset, app_spec=app_spec, python_executable=executable)


def compile_hooksets(
    hookset: HookSet,
    *,
    provider: ProviderSelection = "all",
    base_dir: str | Path = ".",
    python_executable: str | None = None,
) -> dict[ProviderName, CompiledConfig]:
    """Compile a hookset for every selected provider."""

    return {
        target: compile_hookset(
            hookset,
            provider=target,
            base_dir=base_dir,
            python_executable=python_executable,
        )
        for target in target_providers(hookset, provider)
    }
