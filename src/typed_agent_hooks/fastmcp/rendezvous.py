"""Stdlib + ``/proc`` only registry/rendezvous primitives for the FastMCP bridge.

Imports **no** ``fastmcp`` (and no codex/claude) so the shim can use it in the
harness's hook subprocess. Linux-only (``/proc`` + ``AF_UNIX`` + ``SO_PEERCRED``);
callers fail open on other platforms.

Registry base (shared by server and shim, computed identically and WITHOUT
depending on ``$XDG_RUNTIME_DIR`` — which codex strips from the MCP server env
while the shim inherits it): prefer the systemd runtime dir derived from euid
(``/run/user/<euid>``, tmpfs, short socket paths) when it is a secure 0700 dir,
else a per-uid dir under ``$TMPDIR``/``/tmp``. Both sides derive the same path by
construction, so no anchor "ROOT" marker is needed.

Anchor: the nearest process-ancestor whose ``comm`` is a known harness
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


def proc_alive(pid: int, starttime: int) -> bool:
    st = read_proc_stat(pid)
    return st is not None and st[1] == starttime


def find_harness_anchor(start_pid: int | None = None) -> tuple[int, int] | None:
    """Walk the ppid chain upward from ``start_pid`` (default ``os.getpid()``);
    return ``(pid, starttime)`` of the nearest ancestor whose ``comm`` is a known
    harness, or ``None``."""
    cur = os.getpid() if start_pid is None else start_pid
    seen: set[int] = set()
    for _ in range(_MAX_ANCESTRY):
        if cur <= 1 or cur in seen:
            break
        seen.add(cur)
        st = read_proc_stat(cur)
        if st is None:
            break
        ppid, starttime, comm = st
        if comm in HARNESS_COMMS:
            return cur, starttime
        cur = ppid
    return None


# --------------------------------------------------------------------------- #
# secure per-uid registry base + anchor dir
# --------------------------------------------------------------------------- #


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
    if explicit is not None:
        base = Path(explicit)
        return base if _ensure_secure_dir(base) else None
    euid = os.geteuid()
    candidates: list[Path] = []
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
