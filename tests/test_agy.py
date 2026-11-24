"""The agy host: its wire schemas, its mapping to shared events and its outputs."""

import json
import os
import subprocess
import sys
from collections import UserDict
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import TypeAdapter, ValidationError

from typed_agent_hooks import agy, claude_code, codex, shared
from typed_agent_hooks.core import parse_json_object, render_json
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
        # Every agy hook names the model.
        ("SessionStart", {"modelName": None}),
        ("SessionStart", {"modelName": 7}),
        # The prompt text and the continuation flag that agy always sends.
        ("PreInvocation", {"lastUserInput": None}),
        ("PreInvocation", {"lastUserInput": ["x"]}),
        ("Stop", {"continuationActive": None}),
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
    path.write_text('{"type": "USER_INPUT"}\n{}\n{"type": "PLANNER_RESPONSE"}\n')

    with pytest.raises(ValueError, match="line 2: a step without a type"):
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

    with pytest.raises(ValidationError, match="nan is not a finite number"):
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


# A lone surrogate is a valid str but not UTF-8, so the output fails to render.
UNRENDERABLE_HOOK = """\
from typed_agent_hooks import shared

app = shared.HookApp(name="rewrite")


@app.on(shared.events.ToolCallProposed)
def proposed(event):
    rewrite = {**event.tool_input, "WaitMsBeforeAsync": ["\\ud800"]}
    return shared.outputs.AllowTool(updated_input=rewrite, system_message="x")


if __name__ == "__main__":
    app.main()
"""


def test_an_output_that_does_not_render_gets_no_note(tmp_path: Path) -> None:
    hook = tmp_path / "rewrite.py"
    hook.write_text(UNRENDERABLE_HOOK, encoding="utf-8")
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
    assert line.startswith("rewrite: UnicodeEncodeError: ")


def test_in_process_callers_read_the_notes_of_the_last_call() -> None:
    app = shared.HookApp(name="deny")
    calls = iter(["Not here.", "\ud800"])

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
    with pytest.raises(UnicodeEncodeError):
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


@pytest.mark.parametrize(
    "reason",
    [
        "TERMINAL_CUSTOM_HOOK",
        "USER_CANCELED",
        "ERROR",
        "MAX_INVOCATIONS",
        "MAX_FORCED_INVOCATIONS",
        "MAX_TOKEN_BUDGET_EXCEEDED",
        "INJECTED_RESPONSE",
    ],
)
def test_a_run_that_the_model_did_not_finish_runs_no_stop_handler(reason: str) -> None:
    # A Stop handler must not continue a turn that a hook refused or the user ended.
    assert _event("Stop", terminationReason=reason) is None
    assert isinstance(
        _event("Stop", terminationReason="TERMINAL_STEP_TYPE"), shared.events.TurnStopped
    )


def test_an_output_that_is_not_utf8_fails_with_no_notes() -> None:
    app = shared.HookApp(name="surrogate")

    @app.on(shared.events.SessionStarted)
    def started(_event: shared.events.SessionStarted) -> shared.outputs.Result:
        return shared.outputs.AddContext(text="file \udcff", system_message="Shown.")

    with pytest.raises(UnicodeEncodeError):
        app.handle("agy", _payload("SessionStart"))
    assert app.notes == []


def test_an_allowed_call_notes_its_omitted_message() -> None:
    event = _event("PreToolUse")
    assert event is not None

    output, notes = to_agy_output(event, shared.outputs.AllowTool(system_message="Shown."))

    assert json.loads(render_json(cast(Any, output))) == {"decision": "allow"}
    assert notes == [
        "agy left out the system_message of AllowTool on ToolCallProposed: "
        "agy shows no informational hook message to the user"
    ]


@pytest.mark.parametrize("reason", ["", "model_stop"])
def test_an_unknown_stop_reason_raises(reason: str) -> None:
    with pytest.raises(ValueError, match="unknown agy terminationReason"):
        _event("Stop", terminationReason=reason)


def test_a_continuation_flag_alone_marks_an_active_stop_hook() -> None:
    event = _event("Stop", continuationActive=True, executionNum=0)
    assert isinstance(event, shared.events.TurnStopped)
    assert event.stop_hook_active is True


def test_a_post_tool_use_without_an_error_key_is_a_completed_call() -> None:
    payload = {key: value for key, value in _payload("PostToolUse").items() if key != "error"}
    assert isinstance(from_agy(agy.parse_input(payload)), shared.events.ToolCallCompleted)


def test_numbers_that_json_lacks_never_reach_a_handler(tmp_path: Path) -> None:
    app = shared.HookApp(name="strict")
    ran: list[str] = []

    @app.on(shared.events.ToolCallProposed)
    def proposed(_event: shared.events.ToolCallProposed) -> shared.outputs.Result:
        ran.append("proposed")
        return shared.outputs.DenyTool(reason="No.")

    @app.on(shared.events.PromptSubmitted)
    def prompted(_event: shared.events.PromptSubmitted) -> shared.outputs.Result:
        ran.append("prompted")
        return shared.outputs.Block(reason="No.")

    text = json.dumps(_payload("PreToolUse"))
    for number in ("Infinity", "-Infinity", "NaN"):
        with pytest.raises(ValueError, match=f"{number.lstrip('-')} is not JSON"):
            app.handle(
                "agy", text.replace('"WaitMsBeforeAsync": 5000', f'"WaitMsBeforeAsync": {number}')
            )
    # Valid JSON that overflows a float, in a field that a model reads.
    for number in ("1e400", "-1e400"):
        with pytest.raises(ValidationError, match="finite number"):
            app.handle(
                "agy", text.replace('"WaitMsBeforeAsync": 5000', f'"WaitMsBeforeAsync": {number}')
            )
    args = {"CommandLine": "x", "WaitMsBeforeAsync": float("inf")}
    mapping = _payload("PreToolUse", toolCall={"id": "c", "name": "run_command", "args": args})
    with pytest.raises(ValidationError, match="finite number"):
        app.handle("agy", mapping)
    # A model instance inside a mapping is validated again.
    instance = agy.events.ToolCall.model_construct(id="c", name="run_command", args=args)
    with pytest.raises(ValidationError, match="finite number"):
        app.handle("agy", _payload("PreToolUse", toolCall=instance))
    transcript = tmp_path / "transcript_full.jsonl"
    # The error names the line, not the payload.
    transcript.write_text('{"type": "PLANNER_RESPONSE", "x": NaN}\n{"type": "USER_INPUT"}\n')
    with pytest.raises(ValueError, match="transcript_full.jsonl line 1: NaN is not JSON"):
        app.handle(
            "agy", _payload("PreInvocation", transcriptPath=str(transcript), initialNumSteps=2)
        )
    assert ran == []


def test_an_overflowing_number_in_an_ignored_field_is_ignored(tmp_path: Path) -> None:
    text = json.dumps(_payload("PreToolUse", futureMetric=1.0)).replace("1.0", "1e400")
    assert isinstance(from_agy(agy.parse_input(text)), shared.events.ToolCallProposed)
    transcript = tmp_path / "transcript_full.jsonl"
    transcript.write_text('{"type": "USER_INPUT", "x": 1e400}\n')
    assert isinstance(
        _event("PreInvocation", transcriptPath=str(transcript), initialNumSteps=1),
        shared.events.PromptSubmitted,
    )


def test_a_deeply_nested_ignored_field_is_ignored() -> None:
    nested: object = 1.5
    for _ in range(5000):
        nested = [nested]
    assert parse_json_object({"ignored": nested})["ignored"] is nested
    assert isinstance(_event("SessionStart", ignored=nested), shared.events.SessionStarted)


def test_a_rewrite_replaces_whole_top_level_arguments() -> None:
    args = {"CommandLine": "x", "Env": {"A": "1", "B": "2"}}
    mapping = _payload("PreToolUse", toolCall={"id": "c", "name": "run_command", "args": args})
    nested = shared.HookApp(name="nested")

    @nested.on(shared.events.ToolCallProposed)
    def replace_nested(_event: shared.events.ToolCallProposed) -> shared.outputs.Result:
        # A nested object is one argument: replacing it can drop its keys.
        return shared.outputs.AllowTool(updated_input={"CommandLine": "x", "Env": {"A": "1"}})

    assert (rendered := nested.handle("agy", mapping)) is not None
    assert json.loads(rendered) == {
        "decision": "allow",
        "overwrite": {"CommandLine": "x", "Env": {"A": "1"}},
    }
    listed = shared.HookApp(name="listed")

    @listed.on(shared.events.ToolCallProposed)
    def replace_with_list(_event: shared.events.ToolCallProposed) -> shared.outputs.Result:
        return shared.outputs.AllowTool(updated_input=["x"])

    with pytest.raises(SharedOutputError, match="only object tool arguments"):
        listed.handle("agy", mapping)


class _ReadCountingMapping(Mapping[str, object]):
    """A payload that returns a finite number on its first read only."""

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload, self.reads = payload, dict.fromkeys(payload, 0)

    def __getitem__(self, key: str) -> object:
        self.reads[key] += 1
        if key == "toolCall" and self.reads[key] > 1:
            return {"id": "c", "name": "run_command", "args": {"CommandLine": float("inf")}}
        return self.payload[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.payload)

    def __len__(self) -> int:
        return len(self.payload)


def test_a_mapping_payload_is_read_once_and_validated_as_read() -> None:
    app = shared.HookApp(name="once")
    seen: list[object] = []

    @app.on(shared.events.ToolCallProposed)
    def proposed(event: shared.events.ToolCallProposed) -> shared.outputs.Result:
        seen.append(event.tool_input)
        return shared.outputs.DenyTool(reason="No.")

    args = {"CommandLine": 1.0}
    payload = _ReadCountingMapping(
        _payload("PreToolUse", toolCall={"id": "c", "name": "run_command", "args": args})
    )
    app.handle("agy", payload)
    assert seen == [args]
    assert set(payload.reads.values()) == {1}


@pytest.mark.parametrize(
    ("parser", "fixture"),
    [
        (codex.parse_input, "codex_inputs.json"),
        (claude_code.parse_input, "claude_code_inputs.json"),
    ],
)
def test_other_hosts_keep_strict_nested_fields_and_refuse_infinity(
    parser: Any, fixture: str
) -> None:
    payloads = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))
    payload = next(item for item in payloads if item["hook_event_name"] == "PreToolUse")
    for value in (("a", "b"), UserDict({"a": 1}), float("inf")):
        with pytest.raises(ValidationError):
            parser({**payload, "tool_input": {"args": value}})


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            agy.events.PreToolUseInput,
            _payload(
                "PreToolUse",
                toolCall={"id": "c", "name": "run_command", "args": {"x": {"y": ["N"]}}},
            ),
        ),
        *[
            (
                host.events.PreToolUseInput,
                next(
                    item
                    for item in json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))
                    if item["hook_event_name"] == "PreToolUse"
                )
                | {"tool_input": {"x": {"y": ["N"]}}},
            )
            for host, fixture in (
                (codex, "codex_inputs.json"),
                (claude_code, "claude_code_inputs.json"),
            )
        ],
    ],
)
def test_wire_models_refuse_numbers_that_are_not_finite_in_json_mode(
    model: Any, payload: dict[str, object]
) -> None:
    for number in ("NaN", "Infinity", "-Infinity", "1e400"):
        text = json.dumps(payload).replace('"N"', number)
        with pytest.raises(ValidationError, match="finite number"):
            model.model_validate_json(text)
        with pytest.raises(ValidationError, match="finite number"):
            TypeAdapter(model).validate_json(text)


def test_a_parsed_agy_event_validates_again_as_an_instance() -> None:
    payloads = json.loads((FIXTURES / "agy_inputs.json").read_text(encoding="utf-8"))
    for payload in payloads:
        event = agy.parse_input(payload)
        assert type(event).model_validate(event) == event
