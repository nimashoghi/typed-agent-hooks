"""Build the self-bootstrapping public command used by the FastMCP forward shim."""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import json
import shutil
import sys
from urllib.parse import SplitResult, urlsplit, urlunsplit


def _credential_free_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
        if parsed.scheme.casefold() not in {"http", "https"} or parsed.username is None:
            return value
        hostname = parsed.hostname
        if hostname is None:
            return None
        host = f"[{hostname}]" if ":" in hostname else hostname
        netloc = f"{host}:{parsed.port}" if parsed.port is not None else host
    except ValueError:
        return None
    return urlunsplit(
        SplitResult(parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
    )


def self_install_spec() -> str | None:
    """Return the immutable Git requirement used for this installation."""

    try:
        raw = importlib_metadata.distribution("typed-agent-hooks").read_text("direct_url.json")
    except Exception:
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    url = data.get("url")
    vcs = data.get("vcs_info")
    if not isinstance(url, str) or not isinstance(vcs, dict) or vcs.get("vcs") != "git":
        return None
    clean_url = _credential_free_url(url)
    if clean_url is None:
        return None
    requested = vcs.get("requested_revision")
    commit = vcs.get("commit_id")
    ref = commit if isinstance(commit, str) and commit else requested
    return f"git+{clean_url}@{ref}" if isinstance(ref, str) and ref else f"git+{clean_url}"


def forward_command() -> list[str]:
    """Return a self-bootstrapping command for the dedicated forwarding executable."""

    if (spec := self_install_spec()) is None:
        return [sys.executable, "-m", "typed_agent_hooks.fastmcp"]
    if uvx := shutil.which("uvx"):
        prefix = [uvx]
    elif uv := shutil.which("uv"):
        prefix = [uv, "tool", "run"]
    else:
        prefix = ["uvx"]
    return [*prefix, "--from", spec, "tah-fastmcp-forward"]
