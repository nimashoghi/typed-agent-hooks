"""Resolve, validate, and compile ordered hookset collections."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .check import CheckReport, check_hookset
from .compiler import ProviderSelection, compile_hookset, target_providers
from .install import config_dict
from .models import HookCollection, HookSet, ProviderName, read_hookset


@dataclass(frozen=True, slots=True)
class CollectionMember:
    """One resolved hookset belonging to a collection."""

    path: Path
    hookset: HookSet


@dataclass(frozen=True, slots=True)
class CollectionCheckReport:
    """Validation summary for a hook collection and all of its members."""

    name: str
    members: tuple[CheckReport, ...]


def resolve_collection(
    collection: HookCollection,
    *,
    base_dir: str | Path = ".",
) -> tuple[CollectionMember, ...]:
    """Resolve member paths and reject duplicate files or hookset names."""

    root = Path(base_dir).expanduser()
    members: list[CollectionMember] = []
    seen_paths: set[Path] = set()
    seen_names: set[str] = set()
    for value in collection.hooksets:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        if path in seen_paths:
            raise ValueError(f"collection contains the same hookset path twice: {path}")
        seen_paths.add(path)

        hookset = read_hookset(path)
        if hookset.name in seen_names:
            raise ValueError(f"collection contains duplicate hookset name {hookset.name!r}")
        seen_names.add(hookset.name)
        members.append(CollectionMember(path=path, hookset=hookset))
    return tuple(members)


def check_collection(
    collection: HookCollection,
    *,
    base_dir: str | Path = ".",
    python_executable: str | None = None,
    command_prefix: Sequence[str] | None = None,
) -> CollectionCheckReport:
    """Validate every member before returning one collection report."""

    reports = tuple(
        check_hookset(
            member.hookset,
            base_dir=member.path.parent,
            python_executable=python_executable,
            command_prefix=command_prefix,
            collection_name=collection.name,
        )
        for member in resolve_collection(collection, base_dir=base_dir)
    )
    return CollectionCheckReport(name=collection.name, members=reports)


def selected_providers(provider: ProviderSelection) -> tuple[ProviderName, ...]:
    """Expand one provider selection independently of collection membership."""

    if provider == "all":
        return ("codex", "claude_code")
    return (provider,)


def compile_collection(
    collection: HookCollection,
    *,
    provider: ProviderSelection = "all",
    base_dir: str | Path = ".",
    python_executable: str | None = None,
    command_prefix: Sequence[str] | None = None,
) -> tuple[tuple[CollectionMember, ...], dict[ProviderName, list[dict[str, object]]]]:
    """Compile each member for each selected provider it supports."""

    members = resolve_collection(collection, base_dir=base_dir)
    compiled: dict[ProviderName, list[dict[str, object]]] = {
        target: [] for target in selected_providers(provider)
    }
    for member in members:
        allowed = set(target_providers(member.hookset))
        for target in compiled:
            if target not in allowed:
                continue
            config = compile_hookset(
                member.hookset,
                provider=target,
                base_dir=member.path.parent,
                python_executable=python_executable,
                command_prefix=command_prefix,
                collection_name=collection.name,
            )
            compiled[target].append(config_dict(config))
    return members, compiled


def combine_configs(configs: Sequence[dict[str, object]]) -> dict[str, object]:
    """Combine generated provider configs without changing member order."""

    hooks: dict[str, list[object]] = {}
    for config in configs:
        raw_hooks = config.get("hooks")
        if not isinstance(raw_hooks, dict):
            raise ValueError("generated config has non-object 'hooks'")
        for event, raw_groups in raw_hooks.items():
            if not isinstance(event, str) or not isinstance(raw_groups, list):
                raise ValueError("generated hooks must map event names to lists")
            hooks.setdefault(event, []).extend(raw_groups)
    return {"hooks": hooks}
