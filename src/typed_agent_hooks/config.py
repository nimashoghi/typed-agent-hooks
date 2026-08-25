"""Preservation-oriented installation of managed provider hook configuration."""

from __future__ import annotations

import json
import os
import shlex
import tempfile
from collections.abc import Collection, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias, cast

from pydantic import BaseModel

from .internal import APP_MARKER, COLLECTION_MARKER

ProviderName: TypeAlias = Literal["codex", "claude_code"]
ProviderSelection: TypeAlias = ProviderName | Literal["all"]
Scope: TypeAlias = Literal["project", "user"]
ALL_PROVIDERS: tuple[ProviderName, ...] = ("codex", "claude_code")


@dataclass(frozen=True, slots=True)
class ConfigChange:
    """One provider config file considered by a reconciliation."""

    path: Path
    changed: bool


def validate_name(value: str, *, kind: str) -> str:
    """Validate a stable managed application or collection name."""

    import re

    if re.fullmatch(r"[a-z][a-z0-9_-]*", value) is None:
        raise ValueError(f"{kind} must match [a-z][a-z0-9_-]*")
    return value


def selected_providers(provider: ProviderSelection) -> tuple[ProviderName, ...]:
    """Expand one explicit provider selection."""

    if provider == "all":
        return ALL_PROVIDERS
    if provider not in ALL_PROVIDERS:
        raise ValueError("provider must be 'codex', 'claude_code', or 'all'")
    return (provider,)


def default_config_path(
    provider: ProviderName,
    *,
    scope: Scope,
    cwd: str | Path = ".",
) -> Path:
    """Return the standard provider configuration path for one scope."""

    if scope not in {"project", "user"}:
        raise ValueError("scope must be 'project' or 'user'")
    if provider == "codex":
        return (
            Path(cwd) / ".codex" / "hooks.json"
            if scope == "project"
            else Path.home() / ".codex" / "hooks.json"
        )
    return (
        Path(cwd) / ".claude" / "settings.json"
        if scope == "project"
        else Path.home() / ".claude" / "settings.json"
    )


def config_dict(model: BaseModel) -> dict[str, object]:
    """Serialize a typed provider config with provider wire aliases."""

    return cast(dict[str, object], model.model_dump(by_alias=True, exclude_none=True))


def read_json_object(path: str | Path) -> dict[str, object]:
    """Read a JSON object, returning an empty object for a missing file."""

    target = Path(path).expanduser()
    if not target.exists():
        return {}
    decoded: object = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError(f"{target} does not contain a JSON object")
    return cast(dict[str, object], decoded)


def _command_tokens(handler: dict[str, object]) -> list[str]:
    args = handler.get("args")
    if isinstance(args, list) and all(isinstance(value, str) for value in args):
        return cast(list[str], args)
    command = handler.get("command")
    if not isinstance(command, str):
        return []
    try:
        return shlex.split(command)
    except ValueError:
        return []


def _has_marker(handler: dict[str, object], option: str, values: Collection[str]) -> bool:
    tokens = _command_tokens(handler)
    return any(
        token == option and index + 1 < len(tokens) and tokens[index + 1] in values
        for index, token in enumerate(tokens)
    )


def _remove_managed_groups(
    config: dict[str, object],
    *,
    app_names: Collection[str] = (),
    collection_names: Collection[str] = (),
) -> tuple[dict[str, object], dict[str, int]]:
    result = deepcopy(config)
    insertion_points: dict[str, int] = {}
    hooks = result.get("hooks")
    if hooks is None:
        return result, insertion_points
    if not isinstance(hooks, dict):
        raise ValueError("existing config has non-object 'hooks'")
    hooks = cast(dict[str, object], hooks)

    empty_events: list[str] = []
    for event_name, raw_groups in hooks.items():
        if not isinstance(event_name, str) or not isinstance(raw_groups, list):
            raise ValueError("existing hooks must map event names to lists")
        kept_groups: list[object] = []
        for raw_group in raw_groups:
            if not isinstance(raw_group, dict):
                raise ValueError(f"existing hooks.{event_name} contains a non-object group")
            raw_handlers = raw_group.get("hooks")
            if not isinstance(raw_handlers, list):
                raise ValueError(f"existing hooks.{event_name} group has non-list hooks")
            kept_handlers: list[object] = []
            for raw_handler in raw_handlers:
                if not isinstance(raw_handler, dict):
                    raise ValueError(
                        f"existing hooks.{event_name} group contains a non-object handler"
                    )
                handler = cast(dict[str, object], raw_handler)
                managed = _has_marker(handler, APP_MARKER, app_names) or _has_marker(
                    handler, COLLECTION_MARKER, collection_names
                )
                if managed:
                    insertion_points.setdefault(event_name, len(kept_groups))
                else:
                    kept_handlers.append(raw_handler)
            if kept_handlers:
                group = dict(raw_group)
                group["hooks"] = kept_handlers
                kept_groups.append(group)
        if kept_groups:
            hooks[event_name] = kept_groups
        else:
            empty_events.append(event_name)

    for event_name in empty_events:
        del hooks[event_name]
    if not hooks:
        result.pop("hooks", None)
    return result, insertion_points


def _insert_generated_config(
    target: dict[str, object],
    generated: dict[str, object],
    insertion_points: dict[str, int],
) -> None:
    generated_hooks = generated.get("hooks")
    if not isinstance(generated_hooks, dict):
        raise ValueError("generated config has non-object 'hooks'")
    target_hooks = target.setdefault("hooks", {})
    if not isinstance(target_hooks, dict):
        raise ValueError("existing config has non-object 'hooks'")
    target_hooks = cast(dict[str, object], target_hooks)
    for event_name, groups in generated_hooks.items():
        if not isinstance(event_name, str) or not isinstance(groups, list):
            raise ValueError("generated hooks must map event names to lists")
        raw_target = target_hooks.get(event_name)
        if raw_target is None:
            event_groups: list[object] = []
            target_hooks[event_name] = event_groups
        elif isinstance(raw_target, list):
            event_groups = cast(list[object], raw_target)
        else:
            raise ValueError(f"existing hooks.{event_name} is not a list")
        copied = cast(list[object], deepcopy(groups))
        insertion = insertion_points.get(event_name)
        if insertion is None:
            event_groups.extend(copied)
        else:
            event_groups[insertion:insertion] = copied
            insertion_points[event_name] = insertion + len(copied)


def merge_app_config(
    existing: dict[str, object],
    generated: dict[str, object] | None,
    *,
    app_name: str,
) -> dict[str, object]:
    """Replace one application's handlers while preserving unrelated config."""

    merged, insertion_points = _remove_managed_groups(existing, app_names={app_name})
    if generated is not None:
        _insert_generated_config(merged, generated, insertion_points)
    return merged


def merge_collection_config(
    existing: dict[str, object],
    generated: Sequence[dict[str, object]],
    *,
    collection_name: str,
) -> dict[str, object]:
    """Replace an ordered collection while preserving unrelated config."""

    merged, insertion_points = _remove_managed_groups(existing, collection_names={collection_name})
    for config in generated:
        _insert_generated_config(merged, config, insertion_points)
    return merged


def _atomic_write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        temporary.write(rendered)
        temporary_path = Path(temporary.name)
    try:
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _reconcile_file(path: Path, updated: dict[str, object]) -> ConfigChange:
    existing = read_json_object(path)
    changed = updated != existing
    if changed:
        _atomic_write_json(path, updated)
    return ConfigChange(path=path, changed=changed)


def _destinations(
    provider: ProviderSelection,
    *,
    scope: Scope,
    project_root: str | Path,
    target_path: str | Path | None,
) -> dict[ProviderName, Path]:
    providers = selected_providers(provider)
    if target_path is not None and len(providers) != 1:
        raise ValueError("an explicit target path requires exactly one provider")
    return {
        name: (
            Path(target_path).expanduser()
            if target_path is not None
            else default_config_path(name, scope=scope, cwd=project_root)
        )
        for name in providers
    }


def reconcile_app_configs(
    app_name: str,
    generated: Mapping[ProviderName, dict[str, object]],
    *,
    provider: ProviderSelection = "all",
    scope: Scope = "project",
    project_root: str | Path = ".",
    target_path: str | Path | None = None,
) -> dict[ProviderName, ConfigChange]:
    """Reconcile one app across every selected provider, including disabled ones."""

    validate_name(app_name, kind="app name")
    changes: dict[ProviderName, ConfigChange] = {}
    for name, path in _destinations(
        provider, scope=scope, project_root=project_root, target_path=target_path
    ).items():
        existing = read_json_object(path)
        updated = merge_app_config(existing, generated.get(name), app_name=app_name)
        changes[name] = _reconcile_file(path, updated)
    return changes


def reconcile_collection_configs(
    collection_name: str,
    generated: Mapping[ProviderName, Sequence[dict[str, object]]],
    *,
    provider: ProviderSelection = "all",
    scope: Scope = "project",
    project_root: str | Path = ".",
    target_path: str | Path | None = None,
) -> dict[ProviderName, ConfigChange]:
    """Reconcile an ordered collection across every selected provider."""

    validate_name(collection_name, kind="collection name")
    changes: dict[ProviderName, ConfigChange] = {}
    for name, path in _destinations(
        provider, scope=scope, project_root=project_root, target_path=target_path
    ).items():
        existing = read_json_object(path)
        updated = merge_collection_config(
            existing, generated.get(name, ()), collection_name=collection_name
        )
        changes[name] = _reconcile_file(path, updated)
    return changes
