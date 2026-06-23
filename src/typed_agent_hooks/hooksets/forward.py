"""Build a robust, self-bootstrapping launcher for the FastMCP forward shim.

The forward shim runs as a harness command-hook long after install time, in a
process whose environment we do not control. Baking an absolute interpreter
path is brittle: under a ``uv run --with git+...`` launcher that path is an
ephemeral build venv uv garbage-collects, so the hook later fails with exit 127.

Instead generate a ``uvx --from <spec> tah-fastmcp-forward`` command that
re-resolves typed-agent-hooks on demand from a stable source. ``<spec>`` is
pinned to the exact git commit this process was installed from (PEP 610
``direct_url.json``), so the shim matches the running bridge and the immutable
commit is cached by uv (no per-call network).
"""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import json
import shutil

_DISTRIBUTION = "typed-agent-hooks"
_CONSOLE_SCRIPT = "tah-fastmcp-forward"


def self_install_spec() -> str | None:
    """A uv-installable ``git+<url>@<commit>`` spec for the running install.

    Returns ``None`` for non-git installs (editable / wheel / registry), whose
    interpreter path is already stable — there the plain ``-m`` launcher is fine
    and the brittle case (an ephemeral ``uv run --with git+...`` build venv)
    does not arise.
    """

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
    commit = vcs.get("commit_id")
    ref = commit if isinstance(commit, str) and commit else vcs.get("requested_revision")
    return f"git+{url}@{ref}" if isinstance(ref, str) and ref else f"git+{url}"


def _uv_run_prefix() -> list[str]:
    """Absolute ``uvx`` (or ``uv tool run``) so the hook does not depend on PATH."""

    uvx = shutil.which("uvx")
    if uvx:
        return [uvx]
    uv = shutil.which("uv")
    if uv:
        return [uv, "tool", "run"]
    return ["uvx"]  # last resort: resolve on PATH when the hook fires


def uvx_forward_command(spec: str | None = None) -> list[str]:
    """A ``uvx --from <spec> tah-fastmcp-forward`` launcher prefix.

    Pass the result to :func:`compile_hookset` as ``forward_command``. ``spec``
    defaults to :func:`self_install_spec`; if that is ``None`` the bare
    distribution name is used (resolvable only once the package is on a registry).
    """

    resolved = spec or self_install_spec() or _DISTRIBUTION
    return [*_uv_run_prefix(), "--from", resolved, _CONSOLE_SCRIPT]
