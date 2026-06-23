"""Self-bootstrapping forward-command launcher (uvx + self-spec detection)."""

from __future__ import annotations

import pytest

from typed_agent_hooks.hooksets import forward, self_install_spec, uvx_forward_command


class _FakeDist:
    def __init__(self, direct_url: str | None) -> None:
        self._direct_url = direct_url

    def read_text(self, name: str) -> str | None:
        return self._direct_url if name == "direct_url.json" else None


def _patch_dist(monkeypatch: pytest.MonkeyPatch, direct_url: str | None) -> None:
    monkeypatch.setattr(
        forward.importlib_metadata, "distribution", lambda _name: _FakeDist(direct_url)
    )


def test_self_install_spec_git(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_dist(
        monkeypatch,
        '{"url":"https://github.com/o/r","vcs_info":{"vcs":"git","commit_id":"abc123"}}',
    )
    assert self_install_spec() == "git+https://github.com/o/r@abc123"


def test_self_install_spec_git_without_commit_falls_back_to_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_dist(
        monkeypatch,
        '{"url":"https://github.com/o/r","vcs_info":{"vcs":"git","requested_revision":"main"}}',
    )
    assert self_install_spec() == "git+https://github.com/o/r@main"


def test_self_install_spec_non_git_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # Editable / local installs have a stable interpreter; no uvx needed.
    _patch_dist(monkeypatch, '{"url":"file:///x","dir_info":{"editable":true}}')
    assert self_install_spec() is None


def test_self_install_spec_missing_direct_url_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_dist(monkeypatch, None)
    assert self_install_spec() is None


def test_uvx_forward_command_explicit_spec() -> None:
    cmd = uvx_forward_command("git+https://github.com/o/r@abc123")
    # Ends in the uvx --from <spec> <console-script> launcher prefix.
    assert cmd[-3:] == ["--from", "git+https://github.com/o/r@abc123", "tah-fastmcp-forward"]
    # Launches via uvx or `uv tool run`.
    assert cmd[0].endswith("uvx") or cmd[1:3] == ["tool", "run"]
