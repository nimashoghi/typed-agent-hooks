from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from typed_agent_hooks import claude_code, codex
from typed_agent_hooks.fastmcp import ForwardingHooks


def _forwarding() -> ForwardingHooks:
    return ForwardingHooks(
        name="ipi",
        server_name="ipi",
        timeout=40,
        startup_wait=5,
        response_timeout=31,
    )


def test_forwarding_config_includes_every_native_event() -> None:
    forwarding = _forwarding()
    prefix = ["/usr/bin/uvx", "--from", "typed-agent-hooks@abc", "tah-fastmcp-forward"]

    codex_config = forwarding.render("codex", command_prefix=prefix)
    claude_config = forwarding.render("claude_code", command_prefix=prefix)

    codex_hooks = cast(dict[str, Any], codex_config["hooks"])
    claude_hooks = cast(dict[str, Any], claude_config["hooks"])
    assert tuple(codex_hooks) == codex.EVENT_NAMES
    assert tuple(claude_hooks) == claude_code.EVENT_NAMES
    codex_command = next(iter(codex_hooks.values()))[0]["hooks"][0]
    claude_command = next(iter(claude_hooks.values()))[0]["hooks"][0]
    assert codex_command["timeout"] == 40
    assert "tah-fastmcp-forward - --provider codex" in codex_command["command"]
    assert "--managed-app ipi" in codex_command["command"]
    assert claude_command["command"] == "/usr/bin/uvx"
    assert claude_command["args"][:3] == [
        "--from",
        "typed-agent-hooks@abc",
        "tah-fastmcp-forward",
    ]
    assert claude_command["args"][3:6] == ["-", "--provider", "claude_code"]


def test_forwarding_install_is_idempotent_and_preserves_unrelated(tmp_path: Path) -> None:
    path = tmp_path / ".codex" / "hooks.json"
    path.parent.mkdir()
    path.write_text('{"unrelated": 1}\n', encoding="utf-8")
    command = ["/usr/bin/uvx", "--from", "typed-agent-hooks@abc", "tah-fastmcp-forward"]

    first = _forwarding().install(provider="codex", project_root=tmp_path, command_prefix=command)
    second = _forwarding().install(provider="codex", project_root=tmp_path, command_prefix=command)

    assert first["codex"].changed is True
    assert second["codex"].changed is False
    assert json.loads(path.read_text(encoding="utf-8"))["unrelated"] == 1
