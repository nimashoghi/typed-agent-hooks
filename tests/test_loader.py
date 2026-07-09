"""Object-spec parsing + loading (cross-platform; regression for Windows drive colons)."""

from __future__ import annotations

import pytest

from typed_agent_hooks.loader import load_object, split_object_spec


def test_split_module_spec():
    assert split_object_spec("pkg.mod:app") == ("pkg.mod", "app")


def test_split_posix_path_spec():
    assert split_object_spec("hooks/app.py:app") == ("hooks/app.py", "app")


def test_split_windows_drive_path_spec():
    # Regression: the drive colon must not be treated as the spec separator
    # (previously split first-colon -> module "C" -> "No module named 'C'").
    assert split_object_spec(r"C:\x\app.py:app") == (r"C:\x\app.py", "app")


@pytest.mark.parametrize(
    "bad",
    [
        "noseparator",
        "mod:",
        ":app",
        r"C:\x\app.py",  # drive colon only; no object part
        "mod:not-an-identifier",
        "mod:obj.attr",  # dotted attrs are not supported (plain getattr)
    ],
)
def test_split_malformed_specs_raise(bad):
    with pytest.raises(ValueError, match="object spec"):
        split_object_spec(bad)


def test_load_object_from_file(tmp_path):
    (tmp_path / "app.py").write_text("app = 'LOADED'\n", encoding="utf-8")
    assert load_object("app.py:app", base_dir=tmp_path) == "LOADED"
    assert load_object(f"{tmp_path / 'app.py'}:app") == "LOADED"
