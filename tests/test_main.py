"""Run a hook file as the hosts do: ``HOOK_FILE codex|claude`` with the payload on stdin."""

import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from typed_agent_hooks import shared

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_BY_HOST = {"codex": "codex_inputs.json", "claude": "claude_code_inputs.json"}

HOOK = """\
import ctypes
import subprocess
import sys

from typed_agent_hooks import shared

app = shared.HookApp(name="probe")


@app.on(shared.events.SessionStarted)
def session_started(event):
    return shared.outputs.AddContext(text=f"session {event.source}")


@app.on(shared.events.PromptSubmitted)
def prompt_submitted(event):
    return shared.outputs.AddContext(text=f"prompt in {event.context.cwd}")


@app.on(shared.events.ToolCallProposed)
def tool_proposed(event):
    return shared.outputs.AddContext(text=f"proposed {event.tool_input['command']}")


@app.on(shared.events.ToolCallCompleted)
def tool_completed(event):
    return shared.outputs.AddContext(text=f"completed {event.tool_input['command']}")


@app.on(shared.events.ToolCallFailed)
def tool_failed(event):
    return shared.outputs.AddContext(text=f"failed {event.tool_input['command']}")


@app.on(shared.events.PermissionRequested)
def permission_requested(event):
    print("checking the request")
    subprocess.run([sys.executable, "-c", "print('child output')"], check=True)
    ctypes.CDLL(None).puts(b"c library output")
    return shared.outputs.AllowPermission()


@app.on(shared.events.CompactionStarting)
def compaction_starting(event):
    return None


@app.on(shared.events.SubagentStopped)
def subagent_stopped(event):
    print("partial context")
    subprocess.run([sys.executable, "-c", "print('child context')"], check=True)
    raise SystemExit(2)


@app.on(shared.events.TurnStopped)
def turn_stopped(event):
    raise RuntimeError("handler failed\\non two lines")


if __name__ == "__main__":
    app.main()
"""


@pytest.fixture
def hook(tmp_path: Path) -> Path:
    path = tmp_path / "probe.py"
    path.write_text(HOOK, encoding="utf-8")
    return path


def _payload(host: str, event_name: str) -> dict[str, object]:
    payloads = json.loads((FIXTURES / FIXTURE_BY_HOST[host]).read_text(encoding="utf-8"))
    return next(item for item in payloads if item["hook_event_name"] == event_name)


def _run(hook: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(hook), *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize("host", ["codex", "claude"])
@pytest.mark.parametrize(
    ("event_name", "context"),
    [
        ("SessionStart", "session startup"),
        ("UserPromptSubmit", "prompt in /repo"),
        ("PreToolUse", "proposed echo ok"),
        ("PostToolUse", "completed echo ok"),
    ],
)
def test_context_output_matches_the_host_wire(
    hook: Path, host: str, event_name: str, context: str
) -> None:
    result = _run(hook, host, stdin=json.dumps(_payload(host, event_name)))

    assert (result.returncode, result.stderr) == (0, "")
    expected = {"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": context}}
    assert result.stdout == json.dumps(expected, separators=(",", ":")) + "\n"


def test_a_print_at_import_goes_to_stderr(tmp_path: Path) -> None:
    hook = tmp_path / "loud.py"
    hook.write_text('print("helper module loaded")\n' + HOOK, encoding="utf-8")

    result = _run(hook, "codex", stdin=json.dumps(_payload("codex", "SessionStart")))

    assert (result.returncode, result.stderr) == (0, "helper module loaded\n")
    assert json.loads(result.stdout) == {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "session startup",
        }
    }


@pytest.mark.parametrize("host", ["codex", "claude"])
def test_handler_and_child_output_go_to_stderr(hook: Path, host: str) -> None:
    result = _run(hook, host, stdin=json.dumps(_payload(host, "PermissionRequest")))

    assert result.returncode == 0
    assert sorted(result.stderr.splitlines()) == [
        "c library output",
        "checking the request",
        "child output",
    ]
    assert json.loads(result.stdout) == {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "allow"},
        }
    }


@pytest.mark.parametrize("host", ["codex", "claude"])
def test_handler_exit_fails_open_without_its_output(hook: Path, host: str) -> None:
    result = _run(hook, host, stdin=json.dumps(_payload(host, "SubagentStop")))

    assert (result.returncode, result.stdout) == (0, "")
    assert sorted(result.stderr.splitlines()) == [
        "child context",
        "partial context",
        "probe: SystemExit: 2",
    ]


def test_claude_tool_failure_carries_context(hook: Path) -> None:
    result = _run(hook, "claude", stdin=json.dumps(_payload("claude", "PostToolUseFailure")))

    assert (result.returncode, result.stderr) == (0, "")
    assert result.stdout == (
        '{"hookSpecificOutput":{"hookEventName":"PostToolUseFailure",'
        '"additionalContext":"failed false"}}\n'
    )


@pytest.mark.parametrize("host", ["codex", "claude"])
def test_handler_returning_none_writes_nothing(hook: Path, host: str) -> None:
    result = _run(hook, host, stdin=json.dumps(_payload(host, "PreCompact")))

    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


@pytest.mark.parametrize(
    ("host", "event_name", "error"),
    [
        ("codex", "Stop", "probe: RuntimeError: handler failed on two lines"),
        ("claude", "Stop", "probe: RuntimeError: handler failed on two lines"),
        ("codex", "SubagentStart", "probe: LookupError: no handler for codex SubagentStart"),
        ("claude", "SubagentStart", "probe: LookupError: no handler for claude SubagentStart"),
        (
            "claude",
            "Notification",
            "probe: ValueError: unsupported Claude Code hook event 'Notification'",
        ),
    ],
)
def test_failures_fail_open_with_one_stderr_line(
    hook: Path, host: str, event_name: str, error: str
) -> None:
    result = _run(hook, host, stdin=json.dumps(_payload(host, event_name)))

    assert (result.returncode, result.stdout) == (0, "")
    assert result.stderr.startswith(error)
    assert result.stderr.count("\n") == 1


@pytest.mark.parametrize("stdin", ["", "not json", "[]", '{"hook_event_name": "PostToolUse"}'])
def test_bad_payload_fails_open_with_one_stderr_line(hook: Path, stdin: str) -> None:
    result = _run(hook, "codex", stdin=stdin)

    assert (result.returncode, result.stdout) == (0, "")
    assert result.stderr.startswith("probe: ")
    assert result.stderr.count("\n") == 1


@pytest.mark.parametrize("args", [(), ("claude_code",), ("codex", "extra")])
def test_bad_host_argument_is_a_usage_error(hook: Path, args: tuple[str, ...]) -> None:
    result = _run(hook, *args, stdin=json.dumps(_payload("codex", "SessionStart")))

    assert (result.returncode, result.stdout) == (1, "")
    assert result.stderr == "usage: probe.py codex|claude < payload.json\n"


def test_a_check_can_read_the_handled_events_without_a_host(hook: Path) -> None:
    app = runpy.run_path(str(hook))["app"]

    handled = {
        host: [shared.native_event_name(event_type, host) for event_type in app.handlers]
        for host in ("codex", "claude")
    }

    # Codex has no ToolCallFailed event, so a host-file check skips None.
    assert handled == {
        "codex": [
            "SessionStart",
            "UserPromptSubmit",
            "PreToolUse",
            "PostToolUse",
            None,
            "PermissionRequest",
            "PreCompact",
            "SubagentStop",
            "Stop",
        ],
        "claude": [
            "SessionStart",
            "UserPromptSubmit",
            "PreToolUse",
            "PostToolUse",
            "PostToolUseFailure",
            "PermissionRequest",
            "PreCompact",
            "SubagentStop",
            "Stop",
        ],
    }


def test_registration_rejects_a_second_handler_for_one_event() -> None:
    app = shared.HookApp(name="twice")

    @app.on(shared.events.PromptSubmitted)
    def first(_event: shared.events.PromptSubmitted) -> shared.outputs.Result:
        return None

    with pytest.raises(ValueError, match="already registered for PromptSubmitted"):

        @app.on(shared.events.PromptSubmitted)
        def second(_event: shared.events.PromptSubmitted) -> shared.outputs.Result:
            return None
