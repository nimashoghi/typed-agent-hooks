"""Hookset validation that intentionally imports and inspects the hook app."""

from dataclasses import dataclass
from pathlib import Path

from typed_agent_hooks import claude_code, codex, shared
from typed_agent_hooks.loader import load_object

from .compiler import compile_hooksets, resolve_app_spec, target_providers
from .models import ClaudeCodeHookSet, CodexHookSet, FastmcpHookSet, HookSet


@dataclass(frozen=True, slots=True)
class CheckReport:
    """Summary returned after validating a hookset and its application."""

    name: str
    mode: str
    providers: tuple[str, ...]
    configured_events: tuple[str, ...]
    extra_handlers: tuple[str, ...]


def check_hookset(
    hookset: HookSet,
    *,
    base_dir: str | Path = ".",
    python_executable: str | None = None,
) -> CheckReport:
    """Compile the hookset, import its app, and verify required handlers exist."""

    compile_hooksets(
        hookset,
        base_dir=base_dir,
        python_executable=python_executable,
    )

    if isinstance(hookset, FastmcpHookSet):
        # No local app to import: the dispatch HookApp lives in the running server.
        return CheckReport(
            name=hookset.name,
            mode=hookset.mode,
            providers=tuple(target_providers(hookset)),
            configured_events=tuple(sorted({hook.event for hook in hookset.hooks})),
            extra_handlers=(),
        )

    app_spec = resolve_app_spec(hookset.app, base_dir=base_dir)
    app = load_object(app_spec)

    if isinstance(hookset, CodexHookSet):
        if not isinstance(app, codex.HookApp):
            raise TypeError("Codex hookset app must be codex.HookApp")
    elif isinstance(hookset, ClaudeCodeHookSet):
        if not isinstance(app, claude_code.HookApp):
            raise TypeError("Claude Code hookset app must be claude_code.HookApp")
    elif not isinstance(app, shared.HookApp):
        raise TypeError("shared hookset app must be shared.HookApp")

    configured = {hook.event for hook in hookset.hooks}
    registered = set(app.handlers)
    missing = configured - registered
    if missing:
        names = ", ".join(sorted(missing))
        raise ValueError(f"hookset registers events with no app handler: {names}")

    return CheckReport(
        name=hookset.name,
        mode=hookset.mode,
        providers=tuple(target_providers(hookset)),
        configured_events=tuple(sorted(configured)),
        extra_handlers=tuple(sorted(registered - configured)),
    )
