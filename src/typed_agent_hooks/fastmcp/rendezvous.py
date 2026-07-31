"""Stdlib-only registry/rendezvous primitives for the FastMCP bridge.

Imports **no** ``fastmcp`` (and no codex/claude) so the shim can use it in the
harness's hook subprocess. POSIX-only (``AF_UNIX`` + euid ownership): process
identity comes from ``/proc`` on Linux and from a ``ps``(1) snapshot on macOS.
Where the primitives are missing (:func:`supported` false, e.g. native Windows)
:func:`runtime_base` returns ``None`` and callers stay inactive / fail open. A
native Windows port would need named pipes plus a pid+starttime process identity
in place of ``/proc``.

Registry base (shared by server and shim, computed identically and WITHOUT
depending on environment the harness treats unevenly — codex strips
``$XDG_RUNTIME_DIR`` from the MCP server env while the shim inherits it, and
``$TMPDIR`` is similarly untrustworthy on macOS): on Linux prefer the systemd
runtime dir derived from euid (``/run/user/<euid>``, tmpfs, short socket paths)
when it is a secure 0700 dir, else a per-uid dir under ``$TMPDIR``/``/tmp``; on
macOS always the per-uid dir under ``/tmp``. Both sides derive the same path by
construction, so no anchor "ROOT" marker is needed.

Anchor: the nearest process-ancestor whose name is a known harness
(``codex``/``claude``) — the lowest common ancestor of the server and the hook.
Keyed by ``(pid, starttime)`` for pid-reuse safety.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import socket
import stat
import struct
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

HARNESS_COMMS = ("codex", "claude")
_DIR_NAME = "tah-fastmcp"
_DIR_MODE = 0o700
_MAX_ANCESTRY = 64

# --------------------------------------------------------------------------- #
# /proc parsing (bytes-mode; field 2 "comm" can contain spaces and parens)
# --------------------------------------------------------------------------- #


def parse_proc_stat(data: bytes) -> tuple[int, int, str] | None:
    """Pure parse of ``/proc/<pid>/stat`` bytes -> ``(ppid, starttime, comm)``.

    Slices after the LAST ``)`` so a process named e.g. ``(x) 1) R`` cannot
    corrupt the field offsets.
    """
    lp = data.find(b"(")
    rp = data.rfind(b")")
    if lp == -1 or rp == -1 or rp < lp:
        return None
    comm = data[lp + 1 : rp].decode("utf-8", "replace")
    rest = data[rp + 1 :].split()  # rest[0]=state(f3) rest[1]=ppid(f4) rest[19]=starttime(f22)
    try:
        ppid = int(rest[1])
        starttime = int(rest[19])
    except (IndexError, ValueError):
        return None
    return ppid, starttime, comm


def read_proc_stat(pid: int) -> tuple[int, int, str] | None:
    """Return ``(ppid, starttime, comm)`` for ``pid`` or ``None``."""
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            data = f.read()
    except (OSError, ValueError):
        return None
    return parse_proc_stat(data)


# --------------------------------------------------------------------------- #
# darwin process identity (ps(1) snapshot; macOS has no /proc)
# --------------------------------------------------------------------------- #

# `lstart` under LC_ALL=C, e.g. "Thu Jul 31 21:10:33 2026": stable per process
# and second-granular, so it doubles as the pid-reuse guard starttime.
_PS_LSTART_FORMAT = "%a %b %d %H:%M:%S %Y"
_PS_LSTART_FIELDS = 5


def _run_ps(argv: list[str]) -> str | None:
    env = dict(os.environ, LC_ALL="C")
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=5, env=env, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def parse_ps_line(line: str) -> tuple[int, int, int, str] | None:
    """Pure parse of one ``pid ppid lstart comm`` line -> ``(pid, ppid, starttime, name)``.

    ``comm`` is the final field and may contain spaces (macOS reports the full
    executable path), so everything after the fixed-width lstart is the name.
    """
    parts = line.split(None, 2 + _PS_LSTART_FIELDS)
    if len(parts) != 2 + _PS_LSTART_FIELDS + 1:
        return None
    try:
        pid = int(parts[0])
        ppid = int(parts[1])
        started = int(time.mktime(time.strptime(" ".join(parts[2:7]), _PS_LSTART_FORMAT)))
    except (ValueError, OverflowError):
        return None
    return pid, ppid, started, parts[7]


def _darwin_process_table() -> dict[int, tuple[int, int, str]]:
    """One ps(1) pass -> ``{pid: (ppid, starttime, name)}``."""
    out = _run_ps(["ps", "-axo", "pid=,ppid=,lstart=,comm="])
    table: dict[int, tuple[int, int, str]] = {}
    for line in (out or "").splitlines():
        parsed = parse_ps_line(line)
        if parsed is not None:
            pid, ppid, started, name = parsed
            table[pid] = (ppid, started, name)
    return table


def _darwin_process_stat(pid: int) -> tuple[int, int, str] | None:
    out = _run_ps(["ps", "-p", str(pid), "-o", "pid=,ppid=,lstart=,comm="])
    for line in (out or "").splitlines():
        parsed = parse_ps_line(line)
        if parsed is not None and parsed[0] == pid:
            return parsed[1], parsed[2], parsed[3]
    return None


# --------------------------------------------------------------------------- #
# portable process identity
# --------------------------------------------------------------------------- #


def process_stat(pid: int) -> tuple[int, int, str] | None:
    """``(ppid, starttime, name)`` for ``pid`` from the platform's source."""
    if sys.platform == "darwin":
        return _darwin_process_stat(pid)
    return read_proc_stat(pid)


def proc_alive(pid: int, starttime: int) -> bool:
    st = process_stat(pid)
    return st is not None and st[1] == starttime


def _is_harness_name(name: str) -> bool:
    # /proc comm is a bare (possibly truncated) name; macOS ps reports the full
    # executable path. Compare the basename so both spell the harness the same.
    return Path(name).name in HARNESS_COMMS


def find_harness_anchor(start_pid: int | None = None) -> tuple[int, int] | None:
    """Walk the ppid chain upward from ``start_pid`` (default ``os.getpid()``);
    return ``(pid, starttime)`` of the nearest ancestor whose name is a known
    harness, or ``None``."""
    cur = os.getpid() if start_pid is None else start_pid
    table = _darwin_process_table() if sys.platform == "darwin" else None
    seen: set[int] = set()
    for _ in range(_MAX_ANCESTRY):
        if cur <= 1 or cur in seen:
            break
        seen.add(cur)
        st = table.get(cur) if table is not None else read_proc_stat(cur)
        if st is None:
            break
        ppid, starttime, name = st
        if _is_harness_name(name):
            return cur, starttime
        cur = ppid
    return None


# --------------------------------------------------------------------------- #
# secure per-uid registry base + anchor dir
# --------------------------------------------------------------------------- #


def supported() -> bool:
    """True when the platform has the primitives the secure registry needs
    (POSIX euid ownership + ``AF_UNIX``; Linux and macOS in practice).

    A call-time capability check rather than ``sys.platform``: it lets tests
    exercise the real mechanism by deleting the attributes.
    """
    return hasattr(os, "geteuid") and hasattr(socket, "AF_UNIX")


def _verify_secure_dir(path: Path) -> bool:
    """True iff ``path`` is a real directory (not a symlink) owned by euid, 0700."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return (
        stat.S_ISDIR(st.st_mode)
        and not stat.S_ISLNK(st.st_mode)
        and st.st_uid == os.geteuid()
        and stat.S_IMODE(st.st_mode) == _DIR_MODE
    )


def _ensure_secure_dir(path: Path) -> bool:
    if _verify_secure_dir(path):
        return True
    try:
        os.mkdir(path, _DIR_MODE)
    except FileExistsError:
        return _verify_secure_dir(path)  # created concurrently; re-verify strictly
    except OSError:
        return False
    with contextlib.suppress(OSError):
        os.chmod(path, _DIR_MODE)  # mkdir mode is subject to umask
    return _verify_secure_dir(path)


def runtime_base(explicit: Path | None = None) -> Path | None:
    """Per-uid registry base; ``None`` if no secure base is available."""
    if not supported():
        return None  # e.g. native Windows -> bridge inactive, shim no-op
    if explicit is not None:
        base = Path(explicit)
        return base if _ensure_secure_dir(base) else None
    euid = os.geteuid()
    candidates: list[Path] = []
    if sys.platform == "darwin":
        # Deliberately ignore $TMPDIR: macOS points it at per-app launchd dirs,
        # and the harness spawns the server and the hook with different
        # environments, so an env-dependent base would put the two sides in
        # different registries (the same reason $XDG_RUNTIME_DIR is ignored).
        candidates.append(Path("/tmp") / f"{_DIR_NAME}-{euid}")
    else:
        run_user = Path(f"/run/user/{euid}")
        if _verify_secure_dir(run_user):
            candidates.append(run_user / _DIR_NAME)
        tmp = Path(os.environ.get("TMPDIR") or "/tmp")
        candidates.append(tmp / f"{_DIR_NAME}-{euid}")
    for cand in candidates:
        if _ensure_secure_dir(cand):
            return cand
    return None


def anchor_dir(base: Path, anchor: tuple[int, int]) -> Path:
    return base / f"{anchor[0]}-{anchor[1]}"


def ensure_anchor_dir(base: Path, anchor: tuple[int, int]) -> Path | None:
    d = anchor_dir(base, anchor)
    return d if _ensure_secure_dir(d) else None


# --------------------------------------------------------------------------- #
# descriptors
# --------------------------------------------------------------------------- #


@dataclass
class Descriptor:
    server_nonce: str
    socket_path: str
    bound_key: str | None
    pid: int
    starttime: int
    generation: int
    cwd: str
    provider: str
    server_name: str


def new_nonce() -> str:
    return secrets.token_hex(16)


def descriptor_path(anchor: Path, server_nonce: str) -> Path:
    return anchor / f"{server_nonce}.json"


def socket_path(anchor: Path, server_nonce: str) -> Path:
    # Short filename: AF_UNIX paths are capped (~108 bytes). The full nonce stays
    # in the descriptor's stored socket_path (what readers actually use) + as the
    # auth token; only the on-disk socket file name is shortened.
    return anchor / f"{server_nonce[:12]}.sock"


def write_descriptor(anchor: Path, desc: Descriptor) -> Path:
    """Atomically (write-temp + ``os.replace``) write/overwrite the descriptor."""
    final = descriptor_path(anchor, desc.server_nonce)
    tmp = anchor / f".{desc.server_nonce}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(asdict(desc), f)
    os.replace(tmp, final)
    return final


def read_json(path: Path | str) -> dict | None:
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def list_descriptors(anchor: Path) -> list[dict]:
    """All descriptor dicts under ``anchor`` (each annotated with ``_path``)."""
    out: list[dict] = []
    try:
        names = os.listdir(anchor)
    except OSError:
        return out
    for name in names:
        if name.startswith(".") or not name.endswith(".json"):
            continue
        data = read_json(anchor / name)
        if data is None:
            continue
        data["_path"] = str(anchor / name)
        out.append(data)
    return out


def descriptor_is_live(data: dict) -> bool:
    pid, starttime = data.get("pid"), data.get("starttime")
    return isinstance(pid, int) and isinstance(starttime, int) and proc_alive(pid, starttime)


# --------------------------------------------------------------------------- #
# unix-socket connect + peer-uid auth
# --------------------------------------------------------------------------- #


def connect_unix(path: str, timeout: float = 1.0) -> socket.socket | None:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(path)
    except OSError:
        s.close()
        return None
    return s


def peer_uid(sock: socket.socket) -> int | None:
    try:
        creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    except (OSError, AttributeError):
        return None
    _pid, uid, _gid = struct.unpack("3i", creds)
    return uid


# --------------------------------------------------------------------------- #
# pending queue (buffer-and-resolve for own-identity events)
# --------------------------------------------------------------------------- #


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def pending_key_dir(anchor: Path, key: str) -> Path:
    return anchor / "pending" / _hash_key(key)


def enqueue_pending(anchor: Path, key: str, frame: bytes, *, cap: int = 64) -> bool:
    """Buffer one framed request for ``key`` (size-capped, dropping when full)."""
    d = pending_key_dir(anchor, key)
    try:
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d.parent, _DIR_MODE)
        os.chmod(d, _DIR_MODE)
    except OSError:
        return False
    try:
        if sum(1 for n in os.listdir(d) if n.endswith(".req")) >= cap:
            return False
    except OSError:
        return False
    name = f"{time.time_ns()}-{secrets.token_hex(4)}.req"
    tmp = d / f".{name}.tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(frame)
        os.replace(tmp, d / name)
    except OSError:
        return False
    return True


def claim_pending(anchor: Path, key: str, claim_token: str) -> list[bytes]:
    """Atomically claim (single-owner rename) all pending frames for ``key``.

    The directory rename guarantees exactly one caller drains a given batch; a
    racing server's rename fails and returns ``[]``.
    """
    src = pending_key_dir(anchor, key)
    dst = anchor / f"claimed-{claim_token}-{_hash_key(key)}"
    try:
        os.rename(src, dst)
    except OSError:
        return []
    frames: list[bytes] = []
    try:
        for name in sorted(os.listdir(dst)):
            if name.endswith(".req"):
                with contextlib.suppress(OSError):
                    frames.append((dst / name).read_bytes())
    finally:
        _rmtree_quiet(dst)
    return frames


def _rmtree_quiet(path: Path) -> None:
    try:
        for name in os.listdir(path):
            with contextlib.suppress(OSError):
                os.unlink(path / name)
        os.rmdir(path)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# best-effort GC (the real cleanup, since Codex SIGKILLs servers)
# --------------------------------------------------------------------------- #


def prune_descriptor(data: dict) -> None:
    """Unlink a dead server's descriptor + socket (best effort)."""
    for p in (data.get("socket_path"), data.get("_path")):
        if isinstance(p, str):
            with contextlib.suppress(OSError):
                os.unlink(p)


def sweep_base(base: Path, *, max_anchors: int = 32) -> None:
    """Bounded opportunistic GC: drop dead anchors and dead descriptors."""
    try:
        names = os.listdir(base)
    except OSError:
        return
    for name in names[:max_anchors]:
        parts = name.split("-")
        if len(parts) != 2:
            continue
        try:
            hpid, hstart = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        adir = base / name
        if not proc_alive(hpid, hstart):
            for desc in list_descriptors(adir):
                prune_descriptor(desc)
            _rmtree_quiet(adir / "pending")
            _rmtree_quiet(adir)
            continue
        for desc in list_descriptors(adir):
            if not descriptor_is_live(desc):
                prune_descriptor(desc)
