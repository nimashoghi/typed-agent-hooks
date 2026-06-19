"""Unit tests for the stdlib-only fastmcp rendezvous primitives."""

from __future__ import annotations

import os

from typed_agent_hooks.fastmcp import rendezvous as rz


def test_parse_proc_stat_handles_parens_in_comm():
    # comm contains ") " — a naive whitespace split would corrupt the offsets.
    line = b"4242 (weird )proc) R 4200 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 558899 junk"
    assert rz.parse_proc_stat(line) == (4200, 558899, "weird )proc")


def test_parse_proc_stat_comm_with_spaces():
    line = b"7 (my proc) S 3 " + b"0 " * 30
    parsed = rz.parse_proc_stat(line)
    assert parsed is not None and parsed[0] == 3 and parsed[2] == "my proc"


def test_parse_proc_stat_malformed():
    assert rz.parse_proc_stat(b"no parens here") is None


def test_read_proc_stat_self_matches_getppid():
    st = rz.read_proc_stat(os.getpid())
    assert st is not None and st[0] == os.getppid()


def test_proc_alive():
    st = rz.read_proc_stat(os.getpid())
    assert st is not None
    assert rz.proc_alive(os.getpid(), st[1]) is True
    assert rz.proc_alive(os.getpid(), st[1] + 99999) is False
    assert rz.proc_alive(2_000_000_000, 1) is False


def test_find_harness_anchor_picks_nearest_harness(monkeypatch):
    chain = {
        100: (200, 11, "python3"),
        200: (300, 12, "sh"),
        300: (400, 13, "codex"),
        400: (1, 14, "fish"),
    }
    monkeypatch.setattr(rz, "read_proc_stat", lambda pid: chain.get(pid))
    assert rz.find_harness_anchor(100) == (300, 13)


def test_find_harness_anchor_none_when_no_harness(monkeypatch):
    chain = {100: (200, 11, "python3"), 200: (1, 12, "fish")}
    monkeypatch.setattr(rz, "read_proc_stat", lambda pid: chain.get(pid))
    assert rz.find_harness_anchor(100) is None


def test_runtime_base_explicit_is_secure(tmp_path):
    base = tmp_path / "reg"
    got = rz.runtime_base(explicit=base)
    assert got == base and rz._verify_secure_dir(base)


def test_verify_secure_dir_rejects_loose_mode(tmp_path):
    loose = tmp_path / "loose"
    loose.mkdir()
    os.chmod(loose, 0o755)
    assert rz._verify_secure_dir(loose) is False


def test_verify_secure_dir_rejects_symlink(tmp_path):
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(real)
    assert rz._verify_secure_dir(link) is False


def _anchor(tmp_path):
    a = tmp_path / "100-200"
    a.mkdir(mode=0o700)
    return a


def test_descriptor_write_read_list_and_atomic_rebind(tmp_path):
    anchor = _anchor(tmp_path)
    desc = rz.Descriptor(
        server_nonce="abc",
        socket_path=str(rz.socket_path(anchor, "abc")),
        bound_key=None,
        pid=os.getpid(),
        starttime=1,
        generation=1,
        cwd="/x",
        provider="codex",
        server_name="ipi",
    )
    rz.write_descriptor(anchor, desc)
    listed = rz.list_descriptors(anchor)
    assert (
        len(listed) == 1 and listed[0]["server_nonce"] == "abc" and listed[0]["bound_key"] is None
    )
    assert listed[0]["_path"].endswith("abc.json")

    desc.bound_key = "T"
    desc.generation = 2
    rz.write_descriptor(anchor, desc)
    listed = rz.list_descriptors(anchor)
    assert len(listed) == 1 and listed[0]["bound_key"] == "T" and listed[0]["generation"] == 2


def test_pending_enqueue_and_single_owner_claim(tmp_path):
    anchor = _anchor(tmp_path)
    assert rz.enqueue_pending(anchor, "K", b"frame1")
    assert rz.enqueue_pending(anchor, "K", b"frame2")
    frames = rz.claim_pending(anchor, "K", "tok1")
    assert sorted(frames) == [b"frame1", b"frame2"]
    assert rz.claim_pending(anchor, "K", "tok2") == []  # single-owner: already drained


def test_pending_cap_drops_when_full(tmp_path):
    anchor = _anchor(tmp_path)
    for i in range(3):
        assert rz.enqueue_pending(anchor, "K", f"f{i}".encode(), cap=3)
    assert rz.enqueue_pending(anchor, "K", b"overflow", cap=3) is False


def test_descriptor_is_live(tmp_path):
    st = rz.read_proc_stat(os.getpid())
    assert st is not None
    assert rz.descriptor_is_live({"pid": os.getpid(), "starttime": st[1]}) is True
    assert rz.descriptor_is_live({"pid": os.getpid(), "starttime": st[1] + 1}) is False
    assert rz.descriptor_is_live({"pid": "x"}) is False
