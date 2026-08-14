"""Self-bootstrapping hook commands (uvx + self-spec detection)."""

from __future__ import annotations

from pathlib import Path

import pytest

import typed_agent_hooks.hooksets.launcher as launcher
from typed_agent_hooks.hooksets import default_command_prefix, self_install_spec


class _FakeDist:
    def __init__(self, direct_url: str | None) -> None:
        self._direct_url = direct_url

    def read_text(self, name: str) -> str | None:
        return self._direct_url if name == "direct_url.json" else None


def _patch_dist(monkeypatch: pytest.MonkeyPatch, direct_url: str | None) -> None:
    monkeypatch.setattr(
        launcher.importlib_metadata, "distribution", lambda _name: _FakeDist(direct_url)
    )


def test_self_install_spec_git(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_dist(
        monkeypatch,
        '{"url":"https://github.com/o/r","vcs_info":{"vcs":"git","commit_id":"abc123"}}',
    )
    assert self_install_spec() == "git+https://github.com/o/r@abc123"


def test_self_install_spec_does_not_embed_http_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_dist(
        monkeypatch,
        '{"url":"https://x-access-token:secret@github.com/o/r",'
        '"vcs_info":{"vcs":"git","commit_id":"abc123"}}',
    )

    spec = self_install_spec()

    assert spec == "git+https://github.com/o/r@abc123"
    assert "secret" not in spec


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


def test_default_command_prefix_self_bootstraps_git_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        launcher,
        "self_install_spec",
        lambda: "git+https://github.com/o/r@abc123",
    )

    cmd = default_command_prefix(
        "shared",
        python_executable="/ephemeral/python",
        self_bootstrap=True,
    )

    assert cmd[-4:] == [
        "--from",
        "git+https://github.com/o/r@abc123",
        "typed-agent-hooks",
        "run",
    ]
    assert Path(cmd[0]).stem.lower() == "uvx" or cmd[1:3] == ["tool", "run"]


def test_explicit_python_disables_self_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        launcher,
        "self_install_spec",
        lambda: "git+https://github.com/o/r@abc123",
    )

    assert default_command_prefix(
        "fastmcp",
        python_executable="/stable/python",
        self_bootstrap=False,
    ) == ["/stable/python", "-m", "typed_agent_hooks", "forward"]
