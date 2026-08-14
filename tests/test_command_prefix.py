from __future__ import annotations

import pytest

from typed_agent_hooks import claude_code
from typed_agent_hooks.hooksets import compile_hooksets, parse_hookset

SHARED_TOML = """
name = "sources"
mode = "shared"
app = "hooks.py:app"
providers = ["codex", "claude_code"]

[[hooks]]
event = "SessionStarted"
"""


def test_command_prefix_applies_to_every_hookset_mode() -> None:
    prefix = [
        "/usr/bin/uvx",
        "--from",
        "git+https://github.com/o/r@abc123",
        "typed-agent-hooks",
        "run",
    ]

    configs = compile_hooksets(parse_hookset(SHARED_TOML), command_prefix=prefix)

    codex = configs["codex"]
    codex_handler = codex.hooks["SessionStart"][0].hooks[0]
    assert codex_handler.command.startswith(
        "/usr/bin/uvx --from git+https://github.com/o/r@abc123 typed-agent-hooks run shared "
    )

    claude = configs["claude_code"]
    assert isinstance(claude, claude_code.config.SettingsHooks)
    claude_handler = claude.hooks["SessionStart"][0].hooks[0]
    assert claude_handler.command == "/usr/bin/uvx"
    assert claude_handler.args is not None
    assert claude_handler.args[:4] == prefix[1:]
    assert claude_handler.args[4] == "shared"


def test_command_prefix_cannot_be_empty() -> None:
    with pytest.raises(ValueError, match="at least one argument"):
        compile_hooksets(parse_hookset(SHARED_TOML), command_prefix=[])
