"""Strict declarative hookset models parsed from TOML."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from typing import Annotated, Literal, Protocol, TypeAlias, cast

from pydantic import Field, TypeAdapter, model_validator

from typed_agent_hooks import claude_code, codex
from typed_agent_hooks.core import StrictModel
from typed_agent_hooks.shared.events import SharedEventName


class _TomlModule(Protocol):
    def loads(self, value: str) -> dict[str, object]: ...


def _load_toml_module() -> _TomlModule:
    module_name = "tomllib" if sys.version_info >= (3, 11) else "tomli"
    return cast(_TomlModule, import_module(module_name))


_TOML = _load_toml_module()

Mode: TypeAlias = Literal["codex", "claude_code", "shared"]
ProviderName: TypeAlias = Literal["codex", "claude_code"]


def _default_providers() -> list[ProviderName]:
    return ["codex", "claude_code"]


PositiveSeconds = Annotated[int, Field(gt=0)]


class CodexHookSpec(StrictModel):
    """One Codex event registration."""

    event: codex.events.CodexEventName
    matcher: str | None = None
    timeout: PositiveSeconds | None = None
    status_message: str | None = None
    command_windows: str | None = None


class ClaudeCodeHookSpec(StrictModel):
    """One Claude Code event registration."""

    event: claude_code.events.ClaudeEventName
    matcher: str | None = None
    timeout: PositiveSeconds | None = None
    status_message: str | None = None
    condition: str | None = Field(default=None, validation_alias="if", serialization_alias="if")
    async_: bool | None = Field(default=None, validation_alias="async", serialization_alias="async")
    async_rewake: bool | None = Field(
        default=None, validation_alias="asyncRewake", serialization_alias="asyncRewake"
    )
    shell: str | None = None


class SharedCodexOptions(StrictModel):
    """Codex-only overrides for one shared event registration."""

    matcher: str | None = None
    timeout: PositiveSeconds | None = None
    status_message: str | None = None
    command_windows: str | None = None


class SharedClaudeCodeOptions(StrictModel):
    """Claude Code-only overrides for one shared event registration."""

    matcher: str | None = None
    timeout: PositiveSeconds | None = None
    status_message: str | None = None
    condition: str | None = Field(default=None, validation_alias="if", serialization_alias="if")
    async_: bool | None = Field(default=None, validation_alias="async", serialization_alias="async")
    async_rewake: bool | None = Field(
        default=None, validation_alias="asyncRewake", serialization_alias="asyncRewake"
    )
    shell: str | None = None


class SharedHookSpec(StrictModel):
    """One shared semantic event registration."""

    event: SharedEventName
    timeout: PositiveSeconds | None = None
    status_message: str | None = None
    codex: SharedCodexOptions = Field(default_factory=SharedCodexOptions)
    claude_code: SharedClaudeCodeOptions = Field(default_factory=SharedClaudeCodeOptions)


class CodexHookSet(StrictModel):
    """Codex-only hookset."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    mode: Literal["codex"]
    app: str
    hooks: list[CodexHookSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _app_is_valid(self) -> CodexHookSet:
        _validate_app_spec(self.app)
        return self


class ClaudeCodeHookSet(StrictModel):
    """Claude Code-only hookset."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    mode: Literal["claude_code"]
    app: str
    hooks: list[ClaudeCodeHookSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _app_is_valid(self) -> ClaudeCodeHookSet:
        _validate_app_spec(self.app)
        return self


class SharedHookSet(StrictModel):
    """Shared semantic hookset compiled separately for each provider."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    mode: Literal["shared"]
    app: str
    providers: list[ProviderName] = Field(default_factory=_default_providers, min_length=1)
    hooks: list[SharedHookSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _configuration_is_consistent(self) -> SharedHookSet:
        _validate_app_spec(self.app)
        if len(set(self.providers)) != len(self.providers):
            raise ValueError("providers must not contain duplicates")

        for hook in self.hooks:
            if "codex" not in self.providers and hook.codex.model_dump(exclude_none=True):
                raise ValueError(f"hook {hook.event} has Codex options but Codex is not enabled")
            if "claude_code" not in self.providers and hook.claude_code.model_dump(
                exclude_none=True, by_alias=True
            ):
                raise ValueError(
                    f"hook {hook.event} has Claude Code options but Claude Code is not enabled"
                )
        return self


HookSet: TypeAlias = Annotated[
    CodexHookSet | ClaudeCodeHookSet | SharedHookSet,
    Field(discriminator="mode"),
]
HOOKSET_ADAPTER: TypeAdapter[HookSet] = TypeAdapter(HookSet)


def _validate_app_spec(app: str) -> None:
    if ":" not in app:
        raise ValueError("app must be 'module:object' or 'path.py:object'")
    target, object_name = app.split(":", 1)
    if not target or not object_name:
        raise ValueError("app must be 'module:object' or 'path.py:object'")


def parse_hookset(data: str | bytes) -> HookSet:
    """Parse and strictly validate TOML hookset text."""

    text = data.decode() if isinstance(data, bytes) else data
    return HOOKSET_ADAPTER.validate_python(_TOML.loads(text))


def read_hookset(path: str | Path) -> HookSet:
    """Read and strictly validate a hookset TOML file."""

    return parse_hookset(Path(path).expanduser().read_bytes())
