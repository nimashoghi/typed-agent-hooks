"""Bootstrap command for the dedicated forwarding executable."""

from __future__ import annotations

from pathlib import Path

import pytest

from typed_agent_hooks.fastmcp import launcher


class _FakeDist:
    def __init__(self, direct_url: str | None) -> None:
        self._direct_url = direct_url

    def read_text(self, name: str) -> str | None:
        return self._direct_url if name == "direct_url.json" else None


def _patch_dist(monkeypatch: pytest.MonkeyPatch, direct_url: str | None) -> None:
    monkeypatch.setattr(
        launcher.importlib_metadata, "distribution", lambda _name: _FakeDist(direct_url)
    )


def test_self_install_spec_uses_exact_commit_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_dist(
        monkeypatch,
        '{"url":"https://x-access-token:secret@github.com/o/r",'
        '"vcs_info":{"vcs":"git","requested_revision":"main","commit_id":"abc123"}}',
    )

    spec = launcher.self_install_spec()

    assert spec == "git+https://github.com/o/r@abc123"
    assert "secret" not in spec


def test_self_install_spec_falls_back_to_exact_git_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_dist(
        monkeypatch,
        '{"url":"https://github.com/o/r","vcs_info":{"vcs":"git","commit_id":"abc123"}}',
    )

    assert launcher.self_install_spec() == "git+https://github.com/o/r@abc123"


def test_self_install_spec_ignores_non_git_install(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_dist(monkeypatch, '{"url":"file:///x","dir_info":{"editable":true}}')
    assert launcher.self_install_spec() is None


def test_forward_command_self_bootstraps_the_dedicated_entry_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(launcher, "self_install_spec", lambda: "git+https://github.com/o/r@abc123")

    command = launcher.forward_command()

    assert command[-3:] == [
        "--from",
        "git+https://github.com/o/r@abc123",
        "tah-fastmcp-forward",
    ]
    assert Path(command[0]).stem.lower() == "uvx" or command[1:3] == ["tool", "run"]


def test_forward_command_uses_current_interpreter_for_local_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(launcher, "self_install_spec", lambda: None)
    assert launcher.forward_command()[1:] == ["-m", "typed_agent_hooks.fastmcp"]
