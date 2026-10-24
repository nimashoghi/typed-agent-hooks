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


@app.on(shared.events.CompactionStarting)
def compaction_starting(event):
    return None


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
        ("claude", "Notification", "probe: NoSharedMappingError: Claude Code event Notification"),
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

    names = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PreCompact", "Stop"]
    assert handled == {"codex": names, "claude": names}


def test_registration_rejects_a_second_handler_for_one_event() -> None:
    app = shared.HookApp(name="twice")

    @app.on(shared.events.PromptSubmitted)
    def first(_event: shared.events.PromptSubmitted) -> shared.outputs.Result:
        return None

    with pytest.raises(ValueError, match="already registered for PromptSubmitted"):

        @app.on(shared.events.PromptSubmitted)
        def second(_event: shared.events.PromptSubmitted) -> shared.outputs.Result:
            return None
