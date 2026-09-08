"""Windows command rendering and execution without shell-dependent quoting."""

import base64
import json
import os
import subprocess
import sys

import pytest

from typed_agent_hooks.shared.app import _windows_command


def test_windows_command_encodes_literal_tokens():
    tokens = [
        r"C:\A & B\O'Brien %TEMP%\hooks.exe",
        "_typed-agent-hooks",
        "--managed-app",
        "foamwiki",
    ]
    rendered = _windows_command(tokens)
    script = base64.b64decode(rendered.split()[-1]).decode("utf-16le")
    assert "O''Brien %TEMP%" in script
    assert script.endswith("; exit $LASTEXITCODE")
    assert "& '" in script
    assert len(rendered.split()) == 5


@pytest.mark.skipif(os.name != "nt", reason="Requires Windows PowerShell")
def test_windows_command_passes_spaces_and_stdin(tmp_path):
    script = tmp_path / "a & b's script.py"
    script.write_text(
        "import sys,json; print(json.dumps([sys.argv[1:], sys.stdin.read()])); sys.exit(7)"
    )
    command = _windows_command(
        [sys.executable, str(script), "space here", "percent%value", "apostrophe's"]
    )
    result = subprocess.run(
        command, shell=True, input="stdin payload", text=True, capture_output=True
    )
    assert result.returncode == 7
    assert json.loads(result.stdout) == [
        ["space here", "percent%value", "apostrophe's"],
        "stdin payload",
    ]
