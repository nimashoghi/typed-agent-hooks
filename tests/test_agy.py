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
    # Only PreInvocation reads lastUserInput, so another event ignores its type.
    assert agy.parse_input(_payload("PostToolUse", lastUserInput=["x"]))
    with pytest.raises(ValidationError):
        agy.parse_input(_payload("Stop", executionNum="1"))


@pytest.mark.parametrize(
    ("event_name", "fields"),
    [
        # The counters that decide prompts and continuations are required.
        ("PreInvocation", {"initialNumSteps": None}),
        ("PreInvocation", {"invocationNum": -1}),
        ("Stop", {"executionNum": None}),
        ("Stop", {"executionNum": -1}),
        # Tool arguments are an object.
        ("PreToolUse", {"toolCall": {"id": "c", "name": "run_command", "args": ["x"]}}),
    ],
)
def test_inputs_reject_missing_counters_and_non_object_arguments(
    event_name: str, fields: dict[str, object]
) -> None:
    payload = {
        key: value for key, value in (_payload(event_name) | fields).items() if value is not None
    }
    with pytest.raises(ValidationError):
        agy.parse_input(payload)


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
        # Any number of hook system messages after the prompt.
        (["USER_INPUT"] + ["SYSTEM_MESSAGE"] * 100, 101, True),
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


def test_a_transcript_shorter_than_its_steps_raises(tmp_path: Path) -> None:
    transcript = _transcript(tmp_path, "USER_INPUT")

    with pytest.raises(ValueError, match="fewer than initialNumSteps"):
        _event("PreInvocation", transcriptPath=transcript, initialNumSteps=2)


def test_a_step_after_the_prefix_is_not_read(tmp_path: Path) -> None:
    path = tmp_path / "transcript_full.jsonl"
    path.write_bytes(b'{"type": "USER_INPUT"}\n\xff\xfe not UTF-8\n')

    event = _event("PreInvocation", transcriptPath=str(path), initialNumSteps=1)

    assert isinstance(event, shared.events.PromptSubmitted)


def test_a_transcript_step_without_a_type_raises(tmp_path: Path) -> None:
    path = tmp_path / "transcript_full.jsonl"
    path.write_text('{}\n{"type": "USER_INPUT"}\n{"type": "PLANNER_RESPONSE"}\n')

    with pytest.raises(ValueError, match="without a type"):
        _event("PreInvocation", transcriptPath=str(path), initialNumSteps=2)


def test_later_model_calls_of_a_run_are_not_prompts_and_read_no_transcript() -> None:
    # The fixture's transcript does not exist.
    assert _event("PreInvocation", invocationNum=3) is None
    assert _event("PreInvocation", initialNumSteps=0) is None


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
            shared.outputs.AddContext(text="Context."),
            {"injectSteps": [{"systemMessage": {"systemMessage": "Context."}}]},
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
            "Stop",
            shared.outputs.Block(reason="Run the tests first."),
            {"decision": "continue", "reason": "Run the tests first."},
        ),
        (
            "PreToolUse",
            shared.outputs.DenyTool(reason="Not allowed."),
            {"decision": "deny", "reason": "Not allowed."},
        ),
        ("PreToolUse", shared.outputs.AllowTool(), {"decision": "allow"}),
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

    output, _notes = to_agy_output(event, cast(Any, result))

    assert json.loads(render_json(cast(Any, output))) == rendered


@pytest.mark.parametrize(
    ("event_name", "result"),
    [
        ("PreToolUse", shared.outputs.AddContext(text="Context.")),
        ("PostToolUse", shared.outputs.AddContext(text="Context.")),
        ("SessionStart", shared.outputs.SystemMessage(message="Checked.")),
        ("PreInvocation", shared.outputs.SystemMessage(message="Checked.")),
        ("PostToolUse", shared.outputs.SystemMessage(message="Checked.")),
        ("Stop", shared.outputs.SystemMessage(message="Checked.")),
        ("PreInvocation", shared.outputs.Stop(reason="Done.")),
        ("Stop", shared.outputs.Stop(reason="Done.")),
        ("PreToolUse", shared.outputs.DenyTool(reason="No.", context="Context.")),
        ("PreToolUse", shared.outputs.AllowTool(updated_input={"CommandLine": "true"})),
        ("PreInvocation", shared.outputs.Block(reason="")),
        ("Stop", shared.outputs.Block(reason="")),
        # agy has no permission-request event.
        ("PreToolUse", shared.outputs.AllowPermission()),
        ("Stop", shared.outputs.DenyPermission(reason="No.")),
    ],
)
def test_results_that_agy_cannot_carry_raise(
    tmp_path: Path, event_name: str, result: object
) -> None:
    event = _prompt(tmp_path) if event_name == "PreInvocation" else _event(event_name)
    assert event is not None

    with pytest.raises(SharedOutputError, match="not supported by agy|needs a reason|not portable"):
        to_agy_output(event, cast(Any, result))


@pytest.mark.parametrize(
    ("event_name", "result"),
    [
        ("SessionStart", shared.outputs.AddContext(text="Context.", system_message="Shown.")),
        ("PreInvocation", shared.outputs.Block(reason="No.", system_message="Shown.")),
        ("Stop", shared.outputs.Block(reason="Go on.", system_message="Shown.")),
        ("PreToolUse", shared.outputs.DenyTool(reason="No.", system_message="Shown.")),
    ],
)
def test_a_system_message_that_agy_cannot_show_is_left_out_with_a_note(
    tmp_path: Path, event_name: str, result: object
) -> None:
    event = _prompt(tmp_path) if event_name == "PreInvocation" else _event(event_name)
    assert event is not None

    output, notes = to_agy_output(event, cast(Any, result))

    assert "Shown." not in render_json(cast(Any, output))
    assert notes == [
        f"agy left out the system_message of {type(result).__name__} on {event.event_name}: "
        "agy shows no informational hook message to the user"
    ]


@pytest.mark.parametrize(
    "handled",
    [
        set(),
        {shared.events.ToolCallCompleted},
        {shared.events.ToolCallFailed},
        {shared.events.ToolCallCompleted, shared.events.ToolCallFailed},
    ],
)
def test_post_tool_use_reaches_the_handler_of_its_kind(
    handled: set[type[shared.events.BaseEvent]],
) -> None:
    # agy sends completed and failed calls as one event, PostToolUse: a hook
    # that handles one kind ignores the other, and one that handles neither fails.
    app = shared.HookApp(name="tools")
    ran: list[str] = []
    for event_type in handled:
        app.on(event_type)(lambda event: ran.append(type(event).__name__))

    for fields, kind in (({}, "ToolCallCompleted"), ({"error": "exit 1"}, "ToolCallFailed")):
        ran.clear()
        payload = _payload("PostToolUse", **fields)
        if not handled:
            with pytest.raises(LookupError, match="no handler"):
                app.handle("agy", payload)
            continue
        assert app.handle("agy", payload) is None
        assert ran == ([kind] if getattr(shared.events, kind) in handled else [])


def test_a_rewrite_is_checked_against_the_arguments_that_agy_sent() -> None:
    app = shared.HookApp(name="rewrite")

    @app.on(shared.events.ToolCallProposed)
    def proposed(event: shared.events.ToolCallProposed) -> shared.outputs.Result:
        assert isinstance(event.tool_input, dict)
        event.tool_input.pop("WaitMsBeforeAsync")
        return shared.outputs.AllowTool(updated_input=event.tool_input)

    # agy merges the rewrite into its arguments, so the removed one would stay.
    with pytest.raises(SharedOutputError, match="cannot remove tool arguments WaitMsBeforeAsync"):
        app.handle("agy", _payload("PreToolUse"))


def test_a_rewrite_with_a_number_that_json_lacks_is_refused() -> None:
    app = shared.HookApp(name="rewrite")

    @app.on(shared.events.ToolCallProposed)
    def proposed(event: shared.events.ToolCallProposed) -> shared.outputs.Result:
        assert isinstance(event.tool_input, dict)
        return shared.outputs.AllowTool(
            updated_input={**event.tool_input, "WaitMsBeforeAsync": float("nan")}
        )

    with pytest.raises(ValueError, match="JSON compliant"):
        app.handle("agy", _payload("PreToolUse"))


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


NAN_HOOK = """\
from typed_agent_hooks import shared

app = shared.HookApp(name="rewrite")


@app.on(shared.events.ToolCallProposed)
def proposed(event):
    rewrite = {**event.tool_input, "WaitMsBeforeAsync": [float("nan")]}
    return shared.outputs.AllowTool(updated_input=rewrite, system_message="x")


if __name__ == "__main__":
    app.main()
"""


def test_an_output_that_does_not_render_gets_no_note(tmp_path: Path) -> None:
    hook = tmp_path / "rewrite.py"
    hook.write_text(NAN_HOOK, encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if key != "PYTHONUNBUFFERED"}

    result = subprocess.run(
        [sys.executable, str(hook), "agy"],
        input=json.dumps(_payload("PreToolUse")),
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )

    assert (result.returncode, result.stdout) == (0, "")
    (line,) = result.stderr.splitlines()
    assert line.startswith("rewrite: ValueError: Out of range float values are not JSON compliant")


def test_in_process_callers_read_the_notes_of_the_last_call() -> None:
    app = shared.HookApp(name="deny")
    calls = iter(["Not here.", float("nan")])

    @app.on(shared.events.ToolCallProposed)
    def proposed(event: shared.events.ToolCallProposed) -> shared.outputs.Result:
        if isinstance(reason := next(calls), str):
            return shared.outputs.DenyTool(reason=reason, system_message="Ask first.")
        assert isinstance(event.tool_input, dict)
        rewrite = {**event.tool_input, "WaitMsBeforeAsync": reason}
        return shared.outputs.AllowTool(updated_input=rewrite, system_message="x")

    assert app.handle("agy", _payload("PreToolUse")) == '{"decision":"deny","reason":"Not here."}'
    assert app.notes == [
        "agy left out the system_message of DenyTool on ToolCallProposed: "
        "agy shows no informational hook message to the user"
    ]
    # A call that fails leaves no notes, also none of the call before it.
    with pytest.raises(ValueError, match="JSON compliant"):
        app.handle("agy", _payload("PreToolUse"))
    assert app.notes == []


DENY_HOOK = """\
from typed_agent_hooks import shared

app = shared.HookApp(name="deny")


@app.on(shared.events.ToolCallProposed)
def proposed(event):
    return shared.outputs.DenyTool(reason="Not here.", system_message="Ask first.")


if __name__ == "__main__":
    app.main()
"""


def test_an_omitted_message_never_stops_the_decision(tmp_path: Path) -> None:
    hook = tmp_path / "deny.py"
    hook.write_text(DENY_HOOK, encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if key != "PYTHONUNBUFFERED"}

    # Also when Python turns every warning into an error.
    result = subprocess.run(
        [sys.executable, "-W", "error", str(hook), "agy"],
        input=json.dumps(_payload("PreToolUse")),
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == {"decision": "deny", "reason": "Not here."}
    assert result.stderr == ""


def test_a_failed_call_leaves_no_notes_of_a_call_inside_it() -> None:
    app = shared.HookApp(name="nested")

    @app.on(shared.events.SessionStarted)
    def started(_event: shared.events.SessionStarted) -> shared.outputs.Result:
        return shared.outputs.AddContext(text="Context.", system_message="Shown.")

    @app.on(shared.events.ToolCallProposed)
    def proposed(_event: shared.events.ToolCallProposed) -> shared.outputs.Result:
        app.handle("agy", _payload("SessionStart"))
        assert app.notes
        return shared.outputs.Stop(reason="Done.")

    with pytest.raises(SharedOutputError):
        app.handle("agy", _payload("PreToolUse"))
    assert app.notes == []
