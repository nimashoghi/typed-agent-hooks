"""Hookset-facing operations used by the command-line interface."""

from __future__ import annotations

from pathlib import Path

from typed_agent_hooks.hooksets import (
    CheckReport,
    ConfigChange,
    ProviderSelection,
    Scope,
    check_hookset,
    compile_hooksets,
    config_dict,
    default_config_path,
    install_config,
    read_hookset,
    target_providers,
    uninstall_config,
)


def check(path: str | Path, *, python_executable: str | None = None) -> CheckReport:
    """Validate a hookset and its imported application."""

    hookset_path = Path(path).expanduser()
    hookset = read_hookset(hookset_path)
    return check_hookset(
        hookset,
        base_dir=hookset_path.parent,
        python_executable=python_executable,
    )


def render(
    path: str | Path,
    *,
    provider: ProviderSelection = "all",
    python_executable: str | None = None,
) -> dict[str, dict[str, object]]:
    """Compile a hookset into provider-native JSON dictionaries."""

    hookset_path = Path(path).expanduser()
    hookset = read_hookset(hookset_path)
    configs = compile_hooksets(
        hookset,
        provider=provider,
        base_dir=hookset_path.parent,
        python_executable=python_executable,
    )
    return {name: config_dict(config) for name, config in configs.items()}


def install(
    path: str | Path,
    *,
    provider: ProviderSelection = "all",
    scope: Scope = "project",
    project_root: str | Path = ".",
    target_path: str | Path | None = None,
    python_executable: str | None = None,
) -> dict[str, ConfigChange]:
    """Check, compile, and idempotently install a hookset."""

    hookset_path = Path(path).expanduser()
    hookset = read_hookset(hookset_path)
    check_hookset(
        hookset,
        base_dir=hookset_path.parent,
        python_executable=python_executable,
    )
    configs = compile_hooksets(
        hookset,
        provider=provider,
        base_dir=hookset_path.parent,
        python_executable=python_executable,
    )
    if target_path is not None and len(configs) != 1:
        raise ValueError("an explicit target path requires exactly one provider")
    if scope not in {"project", "user"}:
        raise ValueError("scope must be 'project' or 'user'")

    changes: dict[str, ConfigChange] = {}
    for provider_name, config in configs.items():
        destination = (
            Path(target_path).expanduser()
            if target_path is not None
            else default_config_path(
                provider_name,
                scope=scope,
                cwd=project_root,
            )
        )
        changes[provider_name] = install_config(
            destination,
            config_dict(config),
            hookset_name=hookset.name,
        )
    return changes


def uninstall(
    path: str | Path,
    *,
    provider: ProviderSelection = "all",
    scope: Scope = "project",
    project_root: str | Path = ".",
    target_path: str | Path | None = None,
) -> dict[str, ConfigChange]:
    """Remove a managed hookset from selected provider configs."""

    hookset = read_hookset(path)
    providers = target_providers(hookset, provider)
    if target_path is not None and len(providers) != 1:
        raise ValueError("an explicit target path requires exactly one provider")
    if scope not in {"project", "user"}:
        raise ValueError("scope must be 'project' or 'user'")

    changes: dict[str, ConfigChange] = {}
    for provider_name in providers:
        destination = (
            Path(target_path).expanduser()
            if target_path is not None
            else default_config_path(
                provider_name,
                scope=scope,
                cwd=project_root,
            )
        )
        changes[provider_name] = uninstall_config(destination, hookset_name=hookset.name)
    return changes
