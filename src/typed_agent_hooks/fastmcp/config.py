"""Code-first provider configuration for a running FastMCP hook bridge."""

from __future__ import annotations

import shlex
from pathlib import Path

from typed_agent_hooks import claude_code, codex
from typed_agent_hooks.config import (
    ConfigChange,
    ProviderName,
    ProviderSelection,
    Scope,
    config_dict,
    reconcile_app_configs,
    validate_name,
)
from typed_agent_hooks.internal import APP_MARKER

from .launcher import forward_command


class ForwardingHooks:
    """Install every provider-native event for one named running bridge."""

    def __init__(
        self,
        *,
        name: str,
        server_name: str,
        timeout: int,
        startup_wait: int,
        response_timeout: int,
    ) -> None:
        self.name = validate_name(name, kind="app name")
        self.server_name = validate_name(server_name, kind="server name")
        for label, value in (
            ("timeout", timeout),
            ("response_timeout", response_timeout),
        ):
            if value <= 0:
                raise ValueError(f"{label} must be positive")
        if startup_wait < 0:
            raise ValueError("startup_wait must not be negative")
        if startup_wait + response_timeout >= timeout:
            raise ValueError("startup_wait + response_timeout must be less than timeout")
        self.timeout = timeout
        self.startup_wait = startup_wait
        self.response_timeout = response_timeout

    @staticmethod
    def events(provider: ProviderName) -> tuple[str, ...]:
        """Return every native event supported by one provider."""

        return tuple(codex.EVENT_NAMES if provider == "codex" else claude_code.EVENT_NAMES)

    def render(
        self,
        provider: ProviderName,
        *,
        command_prefix: list[str] | None = None,
    ) -> dict[str, object]:
        """Render all native events for one provider."""

        prefix = list(command_prefix) if command_prefix is not None else forward_command()
        if not prefix:
            raise ValueError("command_prefix must not be empty")
        args = [
            "-",
            "--provider",
            provider,
            "--server-name",
            self.server_name,
            APP_MARKER,
            self.name,
            "--startup-wait",
            str(self.startup_wait),
            "--response-timeout",
            str(self.response_timeout),
        ]
        if provider == "codex":
            command = codex.config.CommandHook(
                command=shlex.join([*prefix, *args]),
                timeout=self.timeout,
            )
            hooks = {
                event: [codex.config.HookGroup(hooks=[command])] for event in codex.EVENT_NAMES
            }
            return config_dict(codex.config.HooksFile(hooks=hooks))

        command = claude_code.config.CommandHook(
            command=prefix[0],
            args=[*prefix[1:], *args],
            timeout=self.timeout,
        )
        hooks = {
            event: [claude_code.config.HookGroup(hooks=[command])]
            for event in claude_code.EVENT_NAMES
        }
        return config_dict(claude_code.config.SettingsHooks(hooks=hooks))

    def install(
        self,
        *,
        provider: ProviderSelection = "all",
        scope: Scope = "project",
        project_root: str | Path = ".",
        target_path: str | Path | None = None,
        command_prefix: list[str] | None = None,
    ) -> dict[ProviderName, ConfigChange]:
        """Reconcile the forwarding command across selected provider configs."""

        generated: dict[ProviderName, dict[str, object]] = {
            name: self.render(name, command_prefix=command_prefix)
            for name in ("codex", "claude_code")
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
        """Remove this forwarding application from selected provider configs."""

        return reconcile_app_configs(
            self.name,
            {},
            provider=provider,
            scope=scope,
            project_root=project_root,
            target_path=target_path,
        )
