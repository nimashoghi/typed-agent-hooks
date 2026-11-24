"""The agy host: its wire schemas, its mapping to shared events and its outputs."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from typed_agent_hooks import agy, shared
from typed_agent_hooks.core import render_json
from typed_agent_hooks.shared.adapters import from_agy
from typed_agent_hooks.shared.agy_outputs import to_agy_output
from typed_agent_hooks.shared.outputs import SharedOutputError

FIXTURES = Path(__file__).parent / "fixtures"


def _payload(event_name: str, **fields: object) -> dict[str, object]:
    payloads = json.loads((FIXTURES / "agy_inputs.json").read_text(encoding="utf-8"))
    return next(item for item in payloads if item["hookEventName"] == event_name) | fields


def _transcript(tmp_path: Path, *kinds: str) -> str:
    path = tmp_path / "transcript_full.jsonl"
    steps = [json.dumps({"step_index": index, "type": kind}) for index, kind in enumerate(kinds)]
    path.write_text("".join(step + "\n" for step in steps), encoding="utf-8")
    return str(path)


def _event(event_name: str, **fields: object) -> shared.events.AnyEvent | None:
    return from_agy(agy.parse_input(_payload(event_name, **fields)))


def _prompt(tmp_path: Path) -> shared.events.AnyEvent:
    event = _event("PreInvocation", transcriptPath=_transcript(tmp_path, "USER_INPUT"))
    assert isinstance(event, shared.events.PromptSubmitted)
    return event


def test_every_modeled_event_maps_back_to_its_native_name(tmp_path: Path) -> None:
    transcript = _transcript(tmp_path, "USER_INPUT")
    events = [
        _event("SessionStart"),
        _event("PreInvocation", transcriptPath=transcript),
        _event("PreToolUse"),
        _event("PostToolUse"),
        _event("PostToolUse", error="exit status 1"),
        _event("Stop"),
    ]

    for event in events:
        assert event is not None
        assert shared.native_event_name(type(event), "agy") == event.context.source_event
    assert {type(event) for event in events} == set(shared.adapters.NATIVE_EVENT_NAMES["agy"])


def test_context_carries_the_conversation() -> None:
    event = _event("PostToolUse")

    assert isinstance(event, shared.events.ToolCallCompleted)
    assert event.context.host == "agy"
    assert event.context.session_id == "c"
    assert event.context.cwd == "/repo"
    assert event.context.model == "gemini-4-neon-xhigh"
    assert event.context.permission_mode is None
    assert (event.tool_name, event.tool_use_id) == ("run_command", "call_1")
    assert event.tool_input == {
        "CommandLine": "echo ok",
        "WaitMsBeforeAsync": 5000,
        "toolSummary": "Echo",
    }
    # agy gives hooks no tool output.
    assert event.tool_response is None


def test_inputs_ignore_unknown_fields_and_reject_declared_type_drift() -> None:
    assert agy.parse_input(_payload("Stop", unexpected=True)).hook_event_name == "Stop"
    with pytest.raises(ValidationError):
        agy.parse_input(_payload("Stop", executionNum="1"))


@pytest.mark.parametrize("name", ["PostInvocation", "UserPromptSubmit", 7, None])
def test_events_without_a_shared_equivalent_are_rejected(name: object) -> None:
    with pytest.raises(ValueError, match="unsupported agy hook event"):
        agy.parse_input({"hookEventName": name})


@pytest.mark.parametrize(
    ("steps", "initial_num_steps", "is_prompt"),
    [
        (["USER_INPUT"], 1, True),
        # A SessionStart hook injected context after the prompt.
        (["USER_INPUT", "SYSTEM_MESSAGE"], 2, True),
        # Steps that agy wrote after this call started do not count.
        (["USER_INPUT", "PLANNER_RESPONSE"], 1, True),
        # A background message woke the session; agy repeats the old prompt.
        (["USER_INPUT", "PLANNER_RESPONSE"], 2, False),
        (["USER_INPUT", "PLANNER_RESPONSE", "SYSTEM_MESSAGE"], 3, False),
        # The second model call of a turn, after a tool call.
        (["USER_INPUT", "PLANNER_RESPONSE", "GENERIC"], 3, False),
    ],
)
def test_pre_invocation_is_a_prompt_only_when_it_answers_user_input(
    tmp_path: Path, steps: list[str], initial_num_steps: int, is_prompt: bool
) -> None:
    transcript = _transcript(tmp_path, *steps)

    event = _event("PreInvocation", transcriptPath=transcript, initialNumSteps=initial_num_steps)

    if is_prompt:
        assert isinstance(event, shared.events.PromptSubmitted)
        assert event.prompt == "hello"
    else:
        assert event is None


def test_failed_tool_call_and_stop_continuation() -> None:
    failed = _event("PostToolUse", error="exit status 1")
    continued = _event("Stop", executionNum=1)

    assert isinstance(failed, shared.events.ToolCallFailed)
    assert failed.error == "exit status 1"
    assert isinstance(continued, shared.events.TurnStopped)
    assert continued.stop_hook_active is True
    assert isinstance(stopped := _event("Stop"), shared.events.TurnStopped)
    assert stopped.stop_hook_active is False


@pytest.mark.parametrize(
    ("event_name", "result", "rendered"),
    [
        (
            "SessionStart",
            shared.outputs.AddContext(text="Read the guide."),
            {"injectSteps": [{"systemMessage": {"systemMessage": "Read the guide."}}]},
        ),
        (
            "PreInvocation",
            shared.outputs.AddContext(text="Context.", system_message="Shown."),
            {
                "injectSteps": [
                    {"systemMessage": {"systemMessage": "Context."}},
                    {
                        "systemMessage": {
                            "systemMessage": "",
                            "metadata": {"user_markdown": "Shown."},
                        }
                    },
                ]
            },
        ),
        (
            "PreInvocation",
            shared.outputs.Block(reason="Rephrase."),
            {
                "injectSteps": [{"errorMessage": {"userMessage": "Rephrase."}}],
                "terminationBehavior": "terminate",
            },
        ),
        (
            "PreInvocation",
            shared.outputs.Stop(reason="Done."),
            {
                "injectSteps": [{"errorMessage": {"userMessage": "Done."}}],
                "terminationBehavior": "terminate",
            },
        ),
        (
            "Stop",
            shared.outputs.Block(reason="Run the tests first."),
            {"decision": "continue", "reason": "Run the tests first."},
        ),
        (
            "PreToolUse",
            shared.outputs.DenyTool(reason="Not allowed."),
            {"decision": "deny", "reason": "Not allowed."},
        ),
        (
            "PreToolUse",
            shared.outputs.AllowTool(
                updated_input={
                    "CommandLine": "echo safe",
                    "WaitMsBeforeAsync": 5000,
                    "toolSummary": "Echo",
                }
            ),
            {
                "decision": "allow",
                "overwrite": {
                    "CommandLine": "echo safe",
                    "WaitMsBeforeAsync": 5000,
                    "toolSummary": "Echo",
                },
            },
        ),
    ],
)
def test_results_render_the_agy_wire(
    tmp_path: Path, event_name: str, result: object, rendered: dict[str, object]
) -> None:
    event = _prompt(tmp_path) if event_name == "PreInvocation" else _event(event_name)
    assert event is not None

    output = to_agy_output(event, cast(Any, result))

    assert json.loads(render_json(cast(Any, output))) == rendered


@pytest.mark.parametrize(
    ("event_name", "result"),
    [
        ("PreToolUse", shared.outputs.AddContext(text="Context.")),
        ("PostToolUse", shared.outputs.AddContext(text="Context.")),
        ("PostToolUse", shared.outputs.SystemMessage(message="Checked.")),
        ("Stop", shared.outputs.SystemMessage(message="Checked.")),
        ("Stop", shared.outputs.Stop(reason="Done.")),
        ("Stop", shared.outputs.Block(reason="Continue.", system_message="Shown.")),
        ("PreToolUse", shared.outputs.DenyTool(reason="No.", context="Context.")),
        ("PreToolUse", shared.outputs.AllowTool(updated_input={"CommandLine": "true"})),
    ],
)
def test_results_that_agy_cannot_carry_raise(event_name: str, result: object) -> None:
    event = _event(event_name)
    assert event is not None

    with pytest.raises(SharedOutputError, match="not supported by agy"):
        to_agy_output(event, cast(Any, result))


def test_a_hook_for_one_kind_of_finished_tool_call_ignores_the_other() -> None:
    # agy sends completed and failed calls as one event, PostToolUse.
    app = shared.HookApp(name="completed-only")

    @app.on(shared.events.ToolCallCompleted)
    def completed(_event: shared.events.ToolCallCompleted) -> shared.outputs.Result:
        return None

    assert app.handle("agy", _payload("PostToolUse", error="exit status 1")) is None
    with pytest.raises(LookupError, match="no handler"):
        app.handle("agy", _payload("Stop"))


def test_results_outside_the_shared_table_raise_as_in_other_hosts() -> None:
    event = _event("PostToolUse")
    assert event is not None

    with pytest.raises(SharedOutputError, match="not portable"):
        to_agy_output(event, shared.outputs.Stop(reason="Stop here."))


HOOK = """\
from typed_agent_hooks import shared

app = shared.HookApp(name="probe")


@app.on(shared.events.SessionStarted)
def session_started(event):
    return shared.outputs.AddContext(text=f"session {event.context.session_id}")


@app.on(shared.events.PromptSubmitted)
def prompt_submitted(event):
    return shared.outputs.AddContext(text=f"prompt {event.prompt}")


if __name__ == "__main__":
    app.main()
"""


@pytest.mark.parametrize(
    ("event_name", "steps", "stdout"),
    [
        (
            "SessionStart",
            ["USER_INPUT"],
            '{"injectSteps":[{"systemMessage":{"systemMessage":"session c"}}]}\n',
        ),
        (
            "PreInvocation",
            ["USER_INPUT"],
            '{"injectSteps":[{"systemMessage":{"systemMessage":"prompt hello"}}]}\n',
        ),
        # A model call that does not answer the user runs no handler and writes nothing.
        ("PreInvocation", ["USER_INPUT", "PLANNER_RESPONSE"], ""),
    ],
)
def test_main_runs_a_hook_for_agy(
    tmp_path: Path, event_name: str, steps: list[str], stdout: str
) -> None:
    hook = tmp_path / "probe.py"
    hook.write_text(HOOK, encoding="utf-8")
    transcript = _transcript(tmp_path, *steps)
    payload = _payload(event_name, transcriptPath=transcript, initialNumSteps=len(steps))
    env = {key: value for key, value in os.environ.items() if key != "PYTHONUNBUFFERED"}

    result = subprocess.run(
        [sys.executable, str(hook), "agy"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )

    assert (result.returncode, result.stdout, result.stderr) == (0, stdout, "")
