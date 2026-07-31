"""Darwin process-identity primitives: pure parsing plus dispatch, on any OS.

The ``ps``(1) parser and the snapshot ancestry walk are platform-independent
logic fed by recorded output, so unlike the Linux-gated rendezvous suite these
tests run everywhere, exactly like the platform-degrade suite.
"""

from __future__ import annotations

import time

import pytest

from typed_agent_hooks.fastmcp import rendezvous as rz


def _epoch(text: str) -> int:
    return int(time.mktime(time.strptime(text, rz._PS_LSTART_FORMAT)))


def test_parse_ps_line_plain_comm():
    line = "  501   400 Thu Jul 31 21:10:33 2026 /usr/local/bin/codex"
    assert rz.parse_ps_line(line) == (
        501,
        400,
        _epoch("Thu Jul 31 21:10:33 2026"),
        "/usr/local/bin/codex",
    )


def test_parse_ps_line_comm_with_spaces_and_single_digit_day():
    line = "7 1 Fri Jul  4 09:05:01 2026 /Applications/Visual Studio Code.app/helper"
    parsed = rz.parse_ps_line(line)
    assert parsed is not None
    assert parsed[0] == 7 and parsed[1] == 1
    assert parsed[3] == "/Applications/Visual Studio Code.app/helper"


def test_parse_ps_line_malformed():
    assert rz.parse_ps_line("") is None
    assert rz.parse_ps_line("not numbers at all") is None
    assert rz.parse_ps_line("12 34 Thu Jul 31 21:10:33 2026") is None  # no comm


def test_is_harness_name_matches_bare_and_full_paths():
    assert rz._is_harness_name("codex")
    assert rz._is_harness_name("/usr/local/bin/codex")
    assert rz._is_harness_name("/opt/homebrew/bin/claude")
    assert not rz._is_harness_name("/usr/local/bin/codex-helper")
    assert not rz._is_harness_name("python3")


def test_find_harness_anchor_walks_darwin_snapshot(monkeypatch: pytest.MonkeyPatch):
    table = {
        100: (200, 11, "/usr/bin/python3"),
        200: (300, 12, "/bin/sh"),
        300: (400, 13, "/usr/local/bin/codex"),
        400: (1, 14, "/usr/local/bin/fish"),
    }
    monkeypatch.setattr(rz.sys, "platform", "darwin")
    monkeypatch.setattr(rz, "_darwin_process_table", lambda: table)
    assert rz.find_harness_anchor(100) == (300, 13)


def test_find_harness_anchor_darwin_none_without_harness(monkeypatch: pytest.MonkeyPatch):
    table = {100: (200, 11, "/usr/bin/python3"), 200: (1, 12, "/usr/local/bin/fish")}
    monkeypatch.setattr(rz.sys, "platform", "darwin")
    monkeypatch.setattr(rz, "_darwin_process_table", lambda: table)
    assert rz.find_harness_anchor(100) is None


def test_proc_alive_uses_darwin_stat(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(rz.sys, "platform", "darwin")
    monkeypatch.setattr(rz, "_darwin_process_stat", lambda pid: (1, 555, "codex"))
    assert rz.proc_alive(42, 555) is True
    assert rz.proc_alive(42, 556) is False
    monkeypatch.setattr(rz, "_darwin_process_stat", lambda pid: None)
    assert rz.proc_alive(42, 555) is False


def test_runtime_base_on_darwin_ignores_tmpdir(monkeypatch: pytest.MonkeyPatch, tmp_path):
    if not rz.supported():
        pytest.skip("needs POSIX primitives")
    monkeypatch.setattr(rz.sys, "platform", "darwin")
    monkeypatch.setenv("TMPDIR", str(tmp_path / "per-app-tmp"))
    base = rz.runtime_base()
    assert base is not None
    assert str(base).startswith("/tmp/")
    assert str(tmp_path) not in str(base)
