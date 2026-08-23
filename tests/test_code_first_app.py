from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from typed_agent_hooks import shared
from typed_agent_hooks.config import read_json_object
from typed_agent_hooks.core import Provider

FIXTURES = Path(__file__).parent / "fixtures"


def _executable(tmp_path: Path, name: str = "hook.py") -> Path:
    path = tmp_path / name
    path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _payload(event_name: str) -> dict[str, object]:
    payloads = json.loads((FIXTURES / "codex_inputs.json").read_text(encoding="utf-8"))
    return next(item for item in payloads if item["hook_event_name"] == event_name)


def test_handler_and_provider_metadata_are_one_registration(tmp_path: Path) -> None:
    app = shared.HookApp(name="watch", providers=("codex",))

    @app.on(
        shared.events.ToolCallCompleted,
        timeout=15,
        status_message="Watching pull request",
        codex=shared.CodexOptions(matcher="Bash"),
    )
    def completed(_event: shared.events.ToolCallCompleted) -> shared.outputs.Result:
        return shared.outputs.AddContext(text="Watch started.")

    config = app.render("codex", executable=_executable(tmp_path), collection="user-hooks")
    hooks = cast(dict[str, Any], config["hooks"])
    group = hooks["PostToolUse"][0]
    command = group["hooks"][0]

    assert group["matcher"] == "Bash"
    assert command["timeout"] == 15
    assert command["statusMessage"] == "Watching pull request"
    assert "--managed-app watch" in command["command"]
    assert "--managed-collection user-hooks" in command["command"]
    assert app.handle_json(Provider.CODEX, _payload("PostToolUse")) is not None


def test_unsupported_shared_event_fails_for_enabled_provider(tmp_path: Path) -> None:
    app = shared.HookApp(name="failure")

    @app.on(shared.events.ToolCallFailed)
    def failed(_event: shared.events.ToolCallFailed) -> shared.outputs.Result:
        return None

    with pytest.raises(ValueError, match="no Codex equivalent"):
        app.render("codex", executable=_executable(tmp_path))


def test_all_provider_reconciliation_removes_a_disabled_provider(tmp_path: Path) -> None:
    executable = _executable(tmp_path)
    first = shared.HookApp(name="changing")

    @first.on(shared.events.PromptSubmitted)
    def first_prompt(_event: shared.events.PromptSubmitted) -> shared.outputs.Result:
        return None

    first.install(executable=executable, project_root=tmp_path)
    assert "hooks" in read_json_object(tmp_path / ".codex" / "hooks.json")
    assert "hooks" in read_json_object(tmp_path / ".claude" / "settings.json")

    second = shared.HookApp(name="changing", providers=("codex",))

    @second.on(shared.events.PromptSubmitted)
    def second_prompt(_event: shared.events.PromptSubmitted) -> shared.outputs.Result:
        return None

    second.install(executable=executable, project_root=tmp_path)

    assert "hooks" in read_json_object(tmp_path / ".codex" / "hooks.json")
    assert "hooks" not in read_json_object(tmp_path / ".claude" / "settings.json")


def test_reconciliation_preserves_unrelated_config(tmp_path: Path) -> None:
    path = tmp_path / ".codex" / "hooks.json"
    path.parent.mkdir()
    path.write_text('{"other": {"keep": true}}\n', encoding="utf-8")
    app = shared.HookApp(name="example", providers=("codex",))

    @app.on(shared.events.PromptSubmitted)
    def prompt(_event: shared.events.PromptSubmitted) -> shared.outputs.Result:
        return None

    first = app.install(executable=_executable(tmp_path), project_root=tmp_path)
    second = app.install(executable=tmp_path / "hook.py", project_root=tmp_path)

    assert first["codex"].changed is True
    assert second["codex"].changed is False
    assert read_json_object(path)["other"] == {"keep": True}


def test_reinstall_preserves_position_relative_to_other_managed_apps(
    tmp_path: Path,
) -> None:
    first = shared.HookApp(name="first", providers=("codex",))
    second = shared.HookApp(name="second", providers=("codex",))

    @first.on(shared.events.PromptSubmitted)
    def first_prompt(_event: shared.events.PromptSubmitted) -> shared.outputs.Result:
        return None

    @second.on(shared.events.PromptSubmitted)
    def second_prompt(_event: shared.events.PromptSubmitted) -> shared.outputs.Result:
        return None

    first_executable = _executable(tmp_path, "first.py")
    first.install(executable=first_executable, project_root=tmp_path)
    second.install(
        executable=_executable(tmp_path, "second.py"),
        project_root=tmp_path,
    )
    path = tmp_path / ".codex" / "hooks.json"
    before = path.read_text(encoding="utf-8")

    change = first.install(executable=first_executable, project_root=tmp_path)

    assert change["codex"].changed is False
    assert path.read_text(encoding="utf-8") == before
