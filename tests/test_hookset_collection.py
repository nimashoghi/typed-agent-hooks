"""Lifecycle tests for independently owned hooksets managed as one collection."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from typed_agent_hooks.hooksets import HookCollection, parse_hook_target, resolve_collection

PROJECT_ROOT = Path(__file__).parents[1]
SRC = PROJECT_ROOT / "src"


def _run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "typed_agent_hooks", *args],
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _write_hookset(root: Path, *, name: str, event: str) -> Path:
    root.mkdir(parents=True)
    event_type = event
    (root / "hooks.py").write_text(
        "from typed_agent_hooks import shared\n"
        "\n"
        "app = shared.HookApp()\n"
        "\n"
        f"@app.on(shared.events.{event_type})\n"
        "def handle(event):\n"
        "    return None\n",
        encoding="utf-8",
    )
    hookset = root / "hookset.toml"
    hookset.write_text(
        f'name = "{name}"\nmode = "shared"\napp = "hooks.py:app"\n\n[[hooks]]\nevent = "{event}"\n',
        encoding="utf-8",
    )
    return hookset


def _write_collection(path: Path, *members: str) -> None:
    rendered_members = ", ".join(json.dumps(member) for member in members)
    path.write_text(
        f'name = "wiki"\nhooksets = [{rendered_members}]\n',
        encoding="utf-8",
    )


def _commands(config: dict[str, object]) -> list[str]:
    commands: list[str] = []
    hooks = config.get("hooks")
    assert isinstance(hooks, dict)
    for groups in hooks.values():
        assert isinstance(groups, list)
        for group in groups:
            assert isinstance(group, dict)
            handlers = group.get("hooks")
            assert isinstance(handlers, list)
            for handler in handlers:
                assert isinstance(handler, dict)
                command = handler.get("command")
                args = handler.get("args")
                if isinstance(args, list):
                    commands.append(" ".join(str(item) for item in args))
                elif isinstance(command, str):
                    commands.append(command)
    return commands


def test_collection_target_resolves_ordered_members(tmp_path: Path) -> None:
    first = _write_hookset(tmp_path / "first", name="first", event="PromptSubmitted")
    second = _write_hookset(tmp_path / "second", name="second", event="TurnStopped")
    collection_path = tmp_path / "collection.toml"
    _write_collection(collection_path, "first/hookset.toml", "second/hookset.toml")

    target = parse_hook_target(collection_path.read_bytes())
    assert isinstance(target, HookCollection)
    members = resolve_collection(target, base_dir=tmp_path)

    assert [member.path for member in members] == [first, second]
    assert [member.hookset.name for member in members] == ["first", "second"]


def test_collection_reconciles_members_and_preserves_unrelated_hooks(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    hooks_root = project / ".agent-hooks"
    _write_hookset(hooks_root / "first", name="first", event="PromptSubmitted")
    _write_hookset(hooks_root / "second", name="second", event="TurnStopped")
    collection = hooks_root / "collection.toml"
    _write_collection(collection, "first/hookset.toml", "second/hookset.toml")

    codex_path = project / ".codex" / "hooks.json"
    claude_path = project / ".claude" / "settings.json"
    codex_path.parent.mkdir(parents=True)
    claude_path.parent.mkdir(parents=True)
    unrelated_codex = {
        "unrelated": 1,
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other"}]}]},
    }
    unrelated_claude = {"permissions": {"allow": ["Bash"]}}
    codex_path.write_text(json.dumps(unrelated_codex), encoding="utf-8")
    claude_path.write_text(json.dumps(unrelated_claude), encoding="utf-8")

    checked = _run_cli(project, "check", str(collection), "--python", sys.executable)
    assert checked.returncode == 0, checked.stderr
    assert "ok: wiki (2 hooksets)" in checked.stdout
    assert "- first (shared): PromptSubmitted" in checked.stdout
    assert "- second (shared): TurnStopped" in checked.stdout

    rendered = _run_cli(
        project,
        "render",
        str(collection),
        "--provider",
        "codex",
        "--python",
        sys.executable,
    )
    assert rendered.returncode == 0, rendered.stderr
    rendered_commands = _commands(json.loads(rendered.stdout))
    assert all("--hookset-collection wiki" in command for command in rendered_commands)
    assert any("--hookset-name first" in command for command in rendered_commands)
    assert any("--hookset-name second" in command for command in rendered_commands)

    install_args = (
        "install",
        str(collection),
        "--provider",
        "all",
        "--scope",
        "project",
        "--project-root",
        str(project),
        "--python",
        sys.executable,
    )
    first_install = _run_cli(project, *install_args)
    assert first_install.returncode == 0, first_install.stderr
    assert "codex: updated" in first_install.stdout
    assert "claude_code: updated" in first_install.stdout

    installed_codex = json.loads(codex_path.read_text(encoding="utf-8"))
    installed_claude = json.loads(claude_path.read_text(encoding="utf-8"))
    assert installed_codex["unrelated"] == 1
    assert installed_claude["permissions"] == {"allow": ["Bash"]}
    assert sum("--hookset-collection wiki" in item for item in _commands(installed_codex)) == 2
    assert sum("--hookset-collection wiki" in item for item in _commands(installed_claude)) == 2

    repeated = _run_cli(project, *install_args)
    assert repeated.returncode == 0, repeated.stderr
    assert "codex: unchanged" in repeated.stdout
    assert "claude_code: unchanged" in repeated.stdout

    _write_collection(collection, "first/hookset.toml")
    reconciled = _run_cli(project, *install_args)
    assert reconciled.returncode == 0, reconciled.stderr
    installed_codex = json.loads(codex_path.read_text(encoding="utf-8"))
    installed_claude = json.loads(claude_path.read_text(encoding="utf-8"))
    assert sum("--hookset-collection wiki" in item for item in _commands(installed_codex)) == 1
    assert sum("--hookset-collection wiki" in item for item in _commands(installed_claude)) == 1
    assert not any("--hookset-name second" in item for item in _commands(installed_codex))
    assert "other" in _commands(installed_codex)

    uninstalled = _run_cli(
        project,
        "uninstall",
        str(collection),
        "--provider",
        "all",
        "--scope",
        "project",
        "--project-root",
        str(project),
    )
    assert uninstalled.returncode == 0, uninstalled.stderr
    assert json.loads(codex_path.read_text(encoding="utf-8")) == unrelated_codex
    assert json.loads(claude_path.read_text(encoding="utf-8")) == unrelated_claude


def test_collection_rejects_duplicate_hookset_names(tmp_path: Path) -> None:
    _write_hookset(tmp_path / "first", name="duplicate", event="PromptSubmitted")
    _write_hookset(tmp_path / "second", name="duplicate", event="TurnStopped")
    collection = HookCollection(
        name="wiki",
        hooksets=["first/hookset.toml", "second/hookset.toml"],
    )

    with pytest.raises(ValueError, match="duplicate hookset name 'duplicate'"):
        resolve_collection(collection, base_dir=tmp_path)
