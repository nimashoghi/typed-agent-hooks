"""Ordered reconciliation of independently executable hook applications."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterable
from functools import partial
from pathlib import Path

from cyclopts import App
from pydantic_core import to_jsonable_python

from . import claude_code, codex
from .config import (
    ALL_PROVIDERS,
    ConfigChange,
    ProviderName,
    ProviderSelection,
    Scope,
    reconcile_collection_configs,
    validate_name,
)
from .internal import COLLECTION_MARKER, INTERNAL_COMMAND
from .protocol import AppDescription


class Collection:
    """Manage an ordered set of PEP 723 hook executables as one unit."""

    def __init__(self, *, name: str, apps: Iterable[str | Path]) -> None:
        self.name = validate_name(name, kind="collection name")
        self.apps = tuple(Path(app).expanduser() for app in apps)
        if not self.apps:
            raise ValueError("collection must contain at least one app")
        self.cli = App(
            result_action=[
                partial(json.dumps, default=to_jsonable_python, allow_nan=False),
                print,
                "return_zero",
            ]
        )
        self.cli.command(self.install)
        self.cli.command(self.uninstall)

    def describe(self) -> tuple[AppDescription, ...]:
        """Render and validate every child before any provider config is written."""

        descriptions: list[AppDescription] = []
        seen_paths: set[Path] = set()
        seen_names: set[str] = set()
        for raw_path in self.apps:
            path = raw_path.resolve()
            if path in seen_paths:
                raise ValueError(f"collection contains the same app path twice: {path}")
            seen_paths.add(path)
            if not path.is_file():
                raise FileNotFoundError(path)
            command = [
                str(path),
                INTERNAL_COMMAND,
                "describe",
                COLLECTION_MARKER,
                self.name,
            ]
            if sys.platform == "win32":
                command = ["uv", "run", "--script", *command]
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
            if completed.returncode != 0:
                detail = completed.stderr.strip() or completed.stdout.strip()
                raise RuntimeError(f"hook app description failed for {path}: {detail}")
            try:
                description = AppDescription.model_validate_json(completed.stdout)
            except Exception as exc:
                raise ValueError(f"hook app returned an invalid description: {path}") from exc
            if description.name in seen_names:
                raise ValueError(f"collection contains duplicate app name {description.name!r}")
            seen_names.add(description.name)
            if set(description.providers) != set(description.configs):
                raise ValueError(
                    f"hook app {description.name!r} did not render every enabled provider"
                )
            for provider, config in description.configs.items():
                if provider == "codex":
                    codex.config.HooksFile.model_validate(config)
                else:
                    claude_code.config.SettingsHooks.model_validate(config)
            descriptions.append(description)
        return tuple(descriptions)

    def install(
        self,
        *,
        provider: ProviderSelection = "all",
        scope: Scope = "project",
        project_root: str | Path = ".",
        target_path: str | Path | None = None,
    ) -> dict[ProviderName, ConfigChange]:
        """Render all children, then reconcile their configs in declared order."""

        descriptions = self.describe()
        generated: dict[ProviderName, list[dict[str, object]]] = {
            name: [] for name in ALL_PROVIDERS
        }
        for description in descriptions:
            for name, config in description.configs.items():
                generated[name].append(config)
        return reconcile_collection_configs(
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
        """Remove the collection from selected provider configs."""

        return reconcile_collection_configs(
            self.name,
            {},
            provider=provider,
            scope=scope,
            project_root=project_root,
            target_path=target_path,
        )

    def main(self) -> None:
        """Run the CLI generated directly from ``install`` and ``uninstall``."""

        self.cli()
