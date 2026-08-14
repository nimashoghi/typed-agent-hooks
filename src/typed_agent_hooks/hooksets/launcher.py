"""Build robust, self-bootstrapping commands for installed hooksets.

Hooks run long after installation, in a process whose environment we do not
control. Baking an interpreter from ``uvx`` or ``uv run --with`` into provider
configuration is brittle because uv may garbage-collect that environment.

When typed-agent-hooks came from Git, the default command therefore uses
``uvx --from <immutable-spec> typed-agent-hooks``. The exact commit comes from
PEP 610 ``direct_url.json``, so uv can cache the environment without checking a
moving Git reference every time a hook fires.
"""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import json
import shutil
from urllib.parse import SplitResult, urlsplit, urlunsplit

_DISTRIBUTION = "typed-agent-hooks"


def _credential_free_url(value: str) -> str | None:
    """Remove HTTP userinfo before a source URL enters provider configuration."""

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
    """Return the immutable Git requirement for the running installation."""

    try:
        raw = importlib_metadata.distribution(_DISTRIBUTION).read_text("direct_url.json")
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
    if not isinstance(url, str) or not url or not isinstance(vcs, dict) or vcs.get("vcs") != "git":
        return None
    url = _credential_free_url(url)
    if url is None:
        return None
    commit = vcs.get("commit_id")
    ref = commit if isinstance(commit, str) and commit else vcs.get("requested_revision")
    return f"git+{url}@{ref}" if isinstance(ref, str) and ref else f"git+{url}"


def _uv_run_prefix() -> list[str]:
    """Use an absolute uv command so installed hooks do not depend on PATH."""

    if uvx := shutil.which("uvx"):
        return [uvx]
    if uv := shutil.which("uv"):
        return [uv, "tool", "run"]
    return ["uvx"]


def default_command_prefix(
    mode: str,
    *,
    python_executable: str,
    self_bootstrap: bool,
) -> list[str]:
    """Return the command prefix that launches one installed hook."""

    subcommand = "forward" if mode == "fastmcp" else "run"
    if self_bootstrap and (spec := self_install_spec()) is not None:
        return [
            *_uv_run_prefix(),
            "--from",
            spec,
            "typed-agent-hooks",
            subcommand,
        ]
    return [python_executable, "-m", "typed_agent_hooks", subcommand]
