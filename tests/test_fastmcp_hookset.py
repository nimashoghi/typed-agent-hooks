"""Lifecycle tests for the ``mode = "fastmcp"`` hookset (forward-command install)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from typed_agent_hooks import claude_code
from typed_agent_hooks.commands import hookset as hookset_commands
from typed_agent_hooks.hooksets import check_hookset, compile_hooksets, parse_hookset
from typed_agent_hooks.hooksets.models import FastmcpHookSet

CODEX_TOML = """
name = "ipi-hooks"
mode = "fastmcp"
provider = "codex"
server = "ipi"

[[hooks]]
event = "SessionStart"

[[hooks]]
event = "PreToolUse"
matcher = "^(create_kernel|cell)$"
"""

CLAUDE_TOML = """
name = "ipi-hooks"
mode = "fastmcp"
provider = "claude_code"
server = "ipi"

[[hooks]]
event = "SessionStart"

[[hooks]]
event = "PreToolUse"
matcher = "mcp__ipi__.*"
"""

_PY = "/usr/bin/python3"


def test_parse_fastmcp_hookset():
    hs = parse_hookset(CODEX_TOML)
    assert isinstance(hs, FastmcpHookSet)
    assert hs.provider == "codex" and hs.server == "ipi"
    assert [h.event for h in hs.hooks] == ["SessionStart", "PreToolUse"]


def test_compile_codex_emits_forward_command():
    configs = compile_hooksets(parse_hookset(CODEX_TOML), python_executable=_PY)
    assert set(configs) == {"codex"}
    hooks = configs["codex"].hooks
    assert "SessionStart" in hooks
    group = hooks["PreToolUse"][0]
    assert group.matcher == "^(create_kernel|cell)$"
    cmd = group.hooks[0].command
    assert "forward" in cmd
    assert "--provider codex" in cmd
    assert "--server-name ipi" in cmd
    assert "--hookset-name ipi-hooks" in cmd
    assert " run " not in cmd  # not the local-dispatch command


def test_compile_claude_emits_forward_command():
    configs = compile_hooksets(parse_hookset(CLAUDE_TOML), python_executable=_PY)
    assert set(configs) == {"claude_code"}
    cfg = configs["claude_code"]
    assert isinstance(cfg, claude_code.config.SettingsHooks)
    group = cfg.hooks["PreToolUse"][0]
    assert group.matcher == "mcp__ipi__.*"
    handler = group.hooks[0]
    assert handler.command == _PY
    assert handler.args == [
        "-m",
        "typed_agent_hooks",
        "forward",
        "--provider",
        "claude-code",
        "--server-name",
        "ipi",
        "--hookset-name",
        "ipi-hooks",
    ]


_UVX = ["uvx", "--from", "git+https://github.com/o/r@deadbeef", "tah-fastmcp-forward"]


def test_compile_codex_uses_forward_command_launcher():
    configs = compile_hooksets(parse_hookset(CODEX_TOML), forward_command=_UVX)
    cmd = configs["codex"].hooks["PreToolUse"][0].hooks[0].command
    assert cmd == (
        "uvx --from git+https://github.com/o/r@deadbeef tah-fastmcp-forward "
        "--provider codex --server-name ipi --hookset-name ipi-hooks"
    )
    assert "typed_agent_hooks" not in cmd  # no baked -m launcher; uvx resolves it


def test_compile_claude_uses_forward_command_launcher():
    configs = compile_hooksets(parse_hookset(CLAUDE_TOML), forward_command=_UVX)
    cfg = configs["claude_code"]
    assert isinstance(cfg, claude_code.config.SettingsHooks)
    handler = cfg.hooks["PreToolUse"][0].hooks[0]
    assert handler.command == "uvx"
    assert handler.args == [
        "--from",
        "git+https://github.com/o/r@deadbeef",
        "tah-fastmcp-forward",
        "--provider",
        "claude-code",
        "--server-name",
        "ipi",
        "--hookset-name",
        "ipi-hooks",
    ]


def test_check_needs_no_local_app():
    report = check_hookset(parse_hookset(CODEX_TOML))
    assert report.mode == "fastmcp"
    assert report.providers == ("codex",)
    assert "SessionStart" in report.configured_events
    assert report.extra_handlers == ()


def test_invalid_event_rejected():
    bad = CODEX_TOML.replace('event = "PreToolUse"', 'event = "NotAnEvent"')
    with pytest.raises(ValidationError, match="unsupported codex events"):
        parse_hookset(bad)


def test_install_idempotent_and_uninstall_preserves(tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    toml = project / "ipi-hooks.toml"
    toml.write_text(CODEX_TOML)
    codex_path = project / ".codex" / "hooks.json"
    codex_path.parent.mkdir(parents=True)
    unrelated = {
        "unrelated": 1,
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other"}]}]},
    }
    codex_path.write_text(json.dumps(unrelated), encoding="utf-8")

    kw = {
        "provider": "all",
        "scope": "project",
        "project_root": str(project),
        "target_path": None,
        "python_executable": _PY,
    }
    first = hookset_commands.install(str(toml), **kw)
    assert first["codex"].changed is True
    data = json.loads(codex_path.read_text(encoding="utf-8"))
    assert data["unrelated"] == 1  # unrelated preserved
    assert "PreToolUse" in data["hooks"]  # managed forward hook added

    second = hookset_commands.install(str(toml), **kw)
    assert second["codex"].changed is False  # idempotent

    hookset_commands.uninstall(
        str(toml), provider="all", scope="project", project_root=str(project), target_path=None
    )
    assert json.loads(codex_path.read_text(encoding="utf-8")) == unrelated  # only managed removed
