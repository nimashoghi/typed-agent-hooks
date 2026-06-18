"""Load hook application objects from modules or Python files."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import sys
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path


@contextmanager
def _prepend_sys_path(path: Path) -> Iterator[None]:
    value = str(path)
    sys.path.insert(0, value)
    try:
        yield
    finally:
        with suppress(ValueError):
            sys.path.remove(value)


def _split_spec(spec: str) -> tuple[str, str]:
    if ":" not in spec:
        raise ValueError("object spec must be 'module:object' or 'path.py:object'")
    target, object_name = spec.split(":", 1)
    if not target or not object_name:
        raise ValueError("object spec must be 'module:object' or 'path.py:object'")
    return target, object_name


def _looks_like_path(target: str) -> bool:
    return target.endswith(".py") or "/" in target or "\\" in target


def _load_file(path: Path) -> object:
    if not path.is_file():
        raise FileNotFoundError(path)

    digest = hashlib.sha256(str(path).encode()).hexdigest()[:16]
    module_name = f"_typed_agent_hooks_user_{digest}"
    module_spec = importlib.util.spec_from_file_location(module_name, path)
    if module_spec is None or module_spec.loader is None:
        raise ImportError(f"could not load Python module from {path}")

    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_name] = module
    try:
        with _prepend_sys_path(path.parent):
            module_spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def load_object(spec: str, *, base_dir: str | Path | None = None) -> object:
    """Load ``module:object`` or ``path/to/file.py:object``.

    Args:
        spec: Import target in ``target:attribute`` form.
        base_dir: Directory used to resolve relative Python file paths.

    Returns:
        The requested module attribute.

    Raises:
        ValueError: If ``spec`` is malformed.
        FileNotFoundError: If a referenced Python file does not exist.
        ImportError: If the module cannot be loaded.
        AttributeError: If the requested object does not exist.
    """

    target, object_name = _split_spec(spec)
    if _looks_like_path(target):
        path = Path(target).expanduser()
        if not path.is_absolute() and base_dir is not None:
            path = Path(base_dir).expanduser() / path
        module = _load_file(path.resolve())
    else:
        module = importlib.import_module(target)

    try:
        return getattr(module, object_name)
    except AttributeError as exc:
        raise AttributeError(f"{target!r} has no object {object_name!r}") from exc
