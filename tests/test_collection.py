from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from typed_agent_hooks import Collection


def _app_script(path: Path, *, name: str, text: str) -> Path:
    path.write_text(
        f"""#!{sys.executable}
from typed_agent_hooks import shared

app = shared.HookApp(name={name!r})

@app.on(shared.events.PromptSubmitted)
def prompt(_event):
    return shared.outputs.AddContext(text={text!r})

if __name__ == "__main__":
    app.main()
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _commands(path: Path) -> list[str]:
    config = json.loads(path.read_text(encoding="utf-8"))
    return [group["hooks"][0]["command"] for group in config["hooks"]["UserPromptSubmit"]]


def test_collection_preserves_order_and_removes_deleted_members(tmp_path: Path) -> None:
    first = _app_script(tmp_path / "first.py", name="first", text="first")
    second = _app_script(tmp_path / "second.py", name="second", text="second")
    config = tmp_path / ".codex" / "hooks.json"

    Collection(name="suite", apps=(first, second)).install(project_root=tmp_path)
    assert ["first.py" in command for command in _commands(config)] == [True, False]
    assert ["second.py" in command for command in _commands(config)] == [False, True]

    Collection(name="suite", apps=(second,)).install(project_root=tmp_path)
    commands = _commands(config)
    assert len(commands) == 1
    assert "second.py" in commands[0]
    assert "first.py" not in config.read_text(encoding="utf-8")


def test_collection_preflights_all_children_before_writing(tmp_path: Path) -> None:
    good = _app_script(tmp_path / "good.py", name="good", text="good")
    bad = tmp_path / "bad.py"
    bad.write_text(f"#!{sys.executable}\nraise RuntimeError('broken child')\n", encoding="utf-8")
    bad.chmod(0o755)
    config = tmp_path / ".codex" / "hooks.json"
    config.parent.mkdir()
    original = '{"unrelated": true}\n'
    config.write_text(original, encoding="utf-8")

    with pytest.raises(RuntimeError, match="broken child"):
        Collection(name="suite", apps=(good, bad)).install(project_root=tmp_path)

    assert config.read_text(encoding="utf-8") == original


def test_collection_rejects_duplicate_app_names(tmp_path: Path) -> None:
    first = _app_script(tmp_path / "first.py", name="same", text="first")
    second = _app_script(tmp_path / "second.py", name="same", text="second")

    with pytest.raises(ValueError, match="duplicate app name"):
        Collection(name="suite", apps=(first, second)).describe()


def test_collection_cli_uses_the_public_python_methods(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    collection = Collection(
        name="suite",
        apps=(_app_script(tmp_path / "app.py", name="app", text="context"),),
    )

    command, _, _ = collection.cli.parse_args(["install"])

    assert command == collection.install

    assert collection.cli(["install", "--project-root", str(tmp_path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "claude_code": {
            "path": str(tmp_path / ".claude" / "settings.json"),
            "changed": True,
        },
        "codex": {
            "path": str(tmp_path / ".codex" / "hooks.json"),
            "changed": True,
        },
    }
