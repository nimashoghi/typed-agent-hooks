"""Idempotent installation and removal of managed hookset configuration."""

from __future__ import annotations

import json
import os
import shlex
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias, cast

from pydantic import BaseModel

from .models import ProviderName

Scope: TypeAlias = Literal["project", "user"]


@dataclass(frozen=True, slots=True)
class ConfigChange:
    """Result of installing or uninstalling one provider config file."""

    path: Path
    changed: bool


def default_config_path(
    provider: ProviderName,
    *,
    scope: Scope,
    cwd: str | Path = ".",
) -> Path:
    """Return the standard provider config path for a scope."""

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
    decoded: object = json.loads(target.read_text())
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


def _is_managed_handler(handler: dict[str, object], hookset_name: str) -> bool:
    tokens = _command_tokens(handler)
    for index, token in enumerate(tokens[:-1]):
        if token == "--hookset-name" and tokens[index + 1] == hookset_name:
            return True
    return False


def _remove_managed_groups(config: dict[str, object], hookset_name: str) -> dict[str, object]:
    result = deepcopy(config)
    hooks = result.get("hooks")
    if hooks is None:
        return result
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
                if not _is_managed_handler(handler, hookset_name):
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
    return result


def merge_managed_config(
    existing: dict[str, object],
    generated: dict[str, object],
    *,
    hookset_name: str,
) -> dict[str, object]:
    """Replace this hookset's prior handlers while preserving unrelated config."""

    merged = _remove_managed_groups(existing, hookset_name)
    generated_hooks = generated.get("hooks")
    if not isinstance(generated_hooks, dict):
        raise ValueError("generated config has non-object 'hooks'")
    generated_hooks = cast(dict[str, object], generated_hooks)

    target_hooks = merged.setdefault("hooks", {})
    if not isinstance(target_hooks, dict):
        raise ValueError("existing config has non-object 'hooks'")
    target_hooks = cast(dict[str, object], target_hooks)
    for event_name, groups in generated_hooks.items():
        if not isinstance(event_name, str) or not isinstance(groups, list):
            raise ValueError("generated hooks must map event names to lists")
        raw_target = target_hooks.get(event_name)
        if raw_target is None:
            target: list[object] = []
            target_hooks[event_name] = target
        elif isinstance(raw_target, list):
            target = cast(list[object], raw_target)
        else:
            raise ValueError(f"existing hooks.{event_name} is not a list")
        target.extend(cast(list[object], deepcopy(groups)))
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


def install_config(
    path: str | Path,
    generated: dict[str, object],
    *,
    hookset_name: str,
) -> ConfigChange:
    """Install or update one managed hookset atomically and idempotently."""

    target = Path(path).expanduser()
    existing = read_json_object(target)
    merged = merge_managed_config(existing, generated, hookset_name=hookset_name)
    changed = merged != existing
    if changed:
        _atomic_write_json(target, merged)
    return ConfigChange(path=target, changed=changed)


def uninstall_config(path: str | Path, *, hookset_name: str) -> ConfigChange:
    """Remove one managed hookset while preserving all unrelated config."""

    target = Path(path).expanduser()
    if not target.exists():
        return ConfigChange(path=target, changed=False)
    existing = read_json_object(target)
    updated = _remove_managed_groups(existing, hookset_name)
    changed = updated != existing
    if changed:
        _atomic_write_json(target, updated)
    return ConfigChange(path=target, changed=changed)
