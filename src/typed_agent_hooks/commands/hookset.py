"""Hookset-facing operations used by the command-line interface."""

from collections.abc import Sequence
from pathlib import Path

from typed_agent_hooks.hooksets import (
    CheckReport,
    CollectionCheckReport,
    ConfigChange,
    HookCollection,
    ProviderSelection,
    Scope,
    check_collection,
    check_hookset,
    combine_configs,
    compile_collection,
    compile_hooksets,
    config_dict,
    default_config_path,
    install_collection_config,
    install_config,
    read_hook_target,
    selected_providers,
    target_providers,
    uninstall_collection_config,
    uninstall_config,
)


def check(
    path: str | Path,
    *,
    python_executable: str | None = None,
) -> CheckReport | CollectionCheckReport:
    """Validate a hookset or every member of a collection."""

    target_path = Path(path).expanduser()
    target = read_hook_target(target_path)
    if isinstance(target, HookCollection):
        return check_collection(
            target,
            base_dir=target_path.parent,
            python_executable=python_executable,
        )
    return check_hookset(
        target,
        base_dir=target_path.parent,
        python_executable=python_executable,
    )


def render(
    path: str | Path,
    *,
    provider: ProviderSelection = "all",
    python_executable: str | None = None,
    command_prefix: Sequence[str] | None = None,
) -> dict[str, dict[str, object]]:
    """Compile a hookset or collection into provider-native JSON dictionaries."""

    target_path = Path(path).expanduser()
    target = read_hook_target(target_path)
    if isinstance(target, HookCollection):
        _, compiled = compile_collection(
            target,
            provider=provider,
            base_dir=target_path.parent,
            python_executable=python_executable,
            command_prefix=command_prefix,
        )
        rendered: dict[str, dict[str, object]] = {
            name: combine_configs(configs) for name, configs in compiled.items() if configs
        }
        if not rendered:
            raise ValueError("collection has no hooksets for the selected provider")
        return rendered
    configs = compile_hooksets(
        target,
        provider=provider,
        base_dir=target_path.parent,
        python_executable=python_executable,
        command_prefix=command_prefix,
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
    command_prefix: Sequence[str] | None = None,
) -> dict[str, ConfigChange]:
    """Check, compile, and idempotently install a hookset or collection."""

    target_path_on_disk = Path(path).expanduser()
    target = read_hook_target(target_path_on_disk)
    if isinstance(target, HookCollection):
        check_collection(
            target,
            base_dir=target_path_on_disk.parent,
            python_executable=python_executable,
            command_prefix=command_prefix,
        )
        members, configs = compile_collection(
            target,
            provider=provider,
            base_dir=target_path_on_disk.parent,
            python_executable=python_executable,
            command_prefix=command_prefix,
        )
        providers = selected_providers(provider)
        if target_path is not None and len(providers) != 1:
            raise ValueError("an explicit target path requires exactly one provider")
        if scope not in {"project", "user"}:
            raise ValueError("scope must be 'project' or 'user'")
        hookset_names = {member.hookset.name for member in members}
        return {
            provider_name: install_collection_config(
                (
                    Path(target_path).expanduser()
                    if target_path is not None
                    else default_config_path(provider_name, scope=scope, cwd=project_root)
                ),
                configs[provider_name],
                collection_name=target.name,
                hookset_names=hookset_names,
            )
            for provider_name in providers
        }

    check_hookset(
        target,
        base_dir=target_path_on_disk.parent,
        python_executable=python_executable,
        command_prefix=command_prefix,
    )
    configs = compile_hooksets(
        target,
        provider=provider,
        base_dir=target_path_on_disk.parent,
        python_executable=python_executable,
        command_prefix=command_prefix,
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
            hookset_name=target.name,
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
    """Remove a managed hookset or collection from selected provider configs."""

    target = read_hook_target(path)
    providers = (
        selected_providers(provider)
        if isinstance(target, HookCollection)
        else target_providers(target, provider)
    )
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
        changes[provider_name] = (
            uninstall_collection_config(destination, collection_name=target.name)
            if isinstance(target, HookCollection)
            else uninstall_config(destination, hookset_name=target.name)
        )
    return changes
