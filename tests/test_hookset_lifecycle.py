import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from typed_agent_hooks.hooksets import parse_hookset

PROJECT_ROOT = Path(__file__).parents[1]
SRC = PROJECT_ROOT / "src"


def _run_cli(
    cwd: Path,
    *args: str,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "typed_agent_hooks", *args],
        cwd=cwd,
        env=env,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )


def test_full_shared_hookset_lifecycle_is_idempotent(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    hook_project = project / ".agent-hooks"

    initialized = _run_cli(project, "init", str(hook_project), "--mode", "shared")
    assert initialized.returncode == 0, initialized.stderr

    hookset = hook_project / "hookset.toml"
    checked = _run_cli(project, "check", str(hookset))
    assert checked.returncode == 0, checked.stderr
    assert "ok: agent-hooks (shared)" in checked.stdout

    rendered = _run_cli(
        project,
        "render",
        str(hookset),
        "--provider",
        "all",
        "--pretty",
    )
    assert rendered.returncode == 0, rendered.stderr
    rendered_config = json.loads(rendered.stdout)
    assert set(rendered_config) == {"codex", "claude_code"}

    codex_path = project / ".codex" / "hooks.json"
    claude_path = project / ".claude" / "settings.json"
    codex_path.parent.mkdir(parents=True)
    claude_path.parent.mkdir(parents=True)
    existing_codex = {
        "unrelated": 1,
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other"}]}]},
    }
    codex_path.write_text(json.dumps(existing_codex), encoding="utf-8")
    claude_path.write_text(json.dumps({"permissions": {"allow": ["Bash"]}}), encoding="utf-8")

    first_install = _run_cli(
        project,
        "install",
        str(hookset),
        "--provider",
        "all",
        "--scope",
        "project",
        "--project-root",
        str(project),
    )
    assert first_install.returncode == 0, first_install.stderr
    assert "codex: updated" in first_install.stdout
    assert "claude_code: updated" in first_install.stdout

    installed_codex = json.loads(codex_path.read_text(encoding="utf-8"))
    installed_claude = json.loads(claude_path.read_text(encoding="utf-8"))
    assert installed_codex["unrelated"] == 1
    assert installed_claude["permissions"] == {"allow": ["Bash"]}

    second_install = _run_cli(
        project,
        "install",
        str(hookset),
        "--provider",
        "all",
        "--scope",
        "project",
        "--project-root",
        str(project),
    )
    assert second_install.returncode == 0, second_install.stderr
    assert "codex: unchanged" in second_install.stdout
    assert "claude_code: unchanged" in second_install.stdout
    assert json.loads(codex_path.read_text(encoding="utf-8")) == installed_codex
    assert json.loads(claude_path.read_text(encoding="utf-8")) == installed_claude

    payload = {
        "session_id": "session-1",
        "transcript_path": None,
        "cwd": str(project),
        "hook_event_name": "UserPromptSubmit",
        "model": "gpt-5",
        "permission_mode": "default",
        "turn_id": "turn-1",
        "prompt": "Please refactor this module.",
    }
    ran = _run_cli(
        project,
        "run",
        "shared",
        f"{hook_project / 'hooks.py'}:app",
        "--provider",
        "codex",
        stdin=json.dumps(payload),
    )
    assert ran.returncode == 0, ran.stderr
    assert json.loads(ran.stdout) == {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "Inspect project tests before editing.",
        }
    }

    uninstalled = _run_cli(
        project,
        "uninstall",
        str(hookset),
        "--provider",
        "all",
        "--scope",
        "project",
        "--project-root",
        str(project),
    )
    assert uninstalled.returncode == 0, uninstalled.stderr
    remaining_codex = json.loads(codex_path.read_text(encoding="utf-8"))
    remaining_claude = json.loads(claude_path.read_text(encoding="utf-8"))
    assert remaining_codex == {
        "unrelated": 1,
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other"}]}]},
    }
    assert remaining_claude == {"permissions": {"allow": ["Bash"]}}


def test_run_error_identifies_managed_hookset(tmp_path: Path) -> None:
    app = tmp_path / "hooks.py"
    app.write_text(
        "from typed_agent_hooks import shared\n"
        "\n"
        "app = shared.HookApp()\n"
        "\n"
        "@app.on(shared.events.CompactionFinished)\n"
        "def compacted(event):\n"
        "    return shared.outputs.AddContext(text='context')\n",
        encoding="utf-8",
    )
    payload = {
        "session_id": "session-1",
        "transcript_path": None,
        "cwd": str(tmp_path),
        "hook_event_name": "PostCompact",
        "model": "gpt-5",
        "turn_id": "turn-1",
        "trigger": "manual",
    }

    result = _run_cli(
        tmp_path,
        "run",
        "shared",
        f"{app}:app",
        "--provider",
        "codex",
        "--hookset-name",
        "sources",
        stdin=json.dumps(payload),
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith(
        "ERROR: hookset 'sources': AddContext is not portable for "
        "CompactionFinished (codex PostCompact);"
    )
    assert "SessionStarted(source='compact') instead" in result.stderr


def test_shared_hookset_rejects_options_for_a_disabled_provider() -> None:
    text = """
name = "policy"
mode = "shared"
app = "hooks.py:app"
providers = ["codex"]

[[hooks]]
event = "ToolCallProposed"
[hooks.claude_code]
matcher = "Bash"
"""

    with pytest.raises(ValidationError, match="Claude Code options"):
        parse_hookset(text)


def test_local_hookset_rejects_duplicate_dependencies() -> None:
    text = """
name = "policy"
mode = "shared"
app = "hooks.py:app"
dependencies = ["foam-wiki>=0.4", "foam-wiki>=0.4"]

[[hooks]]
event = "PromptSubmitted"
"""

    with pytest.raises(ValidationError, match="dependencies must not contain duplicates"):
        parse_hookset(text)
