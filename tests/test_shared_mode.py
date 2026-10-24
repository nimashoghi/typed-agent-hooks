import json
from pathlib import Path
from typing import Any, Literal, cast

import pytest

from typed_agent_hooks import claude_code, codex, shared
from typed_agent_hooks.shared.results import SharedOutputError

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_BY_HOST = {"codex": "codex_inputs.json", "claude": "claude_code_inputs.json"}


def _payloads(name: str) -> list[dict[str, object]]:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return data


def _payload(name: str, event_name: str) -> dict[str, object]:
    return next(item for item in _payloads(name) if item["hook_event_name"] == event_name)


@pytest.mark.parametrize("host", ["codex", "claude"])
def test_every_modeled_event_maps_back_to_its_native_name(
    host: Literal["codex", "claude"],
) -> None:
    mapped = set()
    for payload in _payloads(FIXTURE_BY_HOST[host]):
        name = payload["hook_event_name"]
        if host == "codex":
            event = shared.from_codex(codex.parse_input(payload))
        elif name in claude_code.INPUT_TYPES:
            event = shared.from_claude_code(claude_code.parse_input(payload))
        else:
            continue
        assert shared.native_event_name(type(event), host) == name
        mapped.add(type(event))

    # ToolCallFailed is Claude Code-only: Codex has no failure primitive and
    # reports failures inside ordinary PostToolUse responses.
    missing = {shared.events.ToolCallFailed} if host == "codex" else set()
    assert mapped == set(shared.events.EVENT_TYPES) - missing


def test_codex_has_no_native_tool_failure_event() -> None:
    assert shared.native_event_name(shared.events.ToolCallFailed, "codex") is None
    assert shared.native_event_name(shared.events.ToolCallFailed, "claude") == (
        "PostToolUseFailure"
    )


def test_agent_identity_reaches_shared_context() -> None:
    codex_event = shared.from_codex(codex.parse_input(_payload("codex_inputs.json", "PostToolUse")))
    claude_event = shared.from_claude_code(
        claude_code.parse_input(_payload("claude_code_inputs.json", "PostToolUse"))
    )

    # The codex fixture models a subagent-scoped tool event; the Claude one is
    # a main-thread event, which carries no agent identity.
    assert codex_event.context.agent_id == "a"
    assert codex_event.context.agent_type == "explore"
    assert claude_event.context.agent_id is None
    assert claude_event.context.agent_type is None


def test_claude_tool_failure_carries_a_system_message() -> None:
    wire_event = claude_code.parse_input(_payload("claude_code_inputs.json", "PostToolUseFailure"))
    event = shared.from_claude_code(wire_event)

    output = shared.outputs.to_claude_code_output(
        event, shared.outputs.SystemMessage(message="The tool failed.")
    )

    assert claude_code.render_output("PostToolUseFailure", output) == (
        '{"systemMessage":"The tool failed."}'
    )


def test_claude_failure_maps_to_tool_call_failed() -> None:
    wire_event = claude_code.parse_input(_payload("claude_code_inputs.json", "PostToolUseFailure"))

    event = shared.from_claude_code(wire_event)

    assert isinstance(event, shared.events.ToolCallFailed)
    assert event.tool_name == "Bash"
    assert event.error == "Exit code 1\nfailed"
    assert event.is_interrupt is False
    assert event.duration_ms == 18


@pytest.mark.parametrize("event_name", ["UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"])
def test_claude_prompt_identity_is_preserved_without_inventing_a_turn(event_name: str) -> None:
    payload = {**_payload("claude_code_inputs.json", event_name), "prompt_id": "native-prompt"}
    event = shared.from_claude_code(claude_code.parse_input(payload))
    assert event.context.prompt_id == "native-prompt"
    assert getattr(event, "turn_id", None) is None


@pytest.mark.parametrize(
    "event_name", ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"]
)
def test_native_scratchpad_reaches_shared_context(event_name: str) -> None:
    payload = _payload("claude_code_inputs.json", event_name) | {
        "scratchpad_dir": "/tmp/native/scratchpad"
    }
    event = shared.from_claude_code(claude_code.parse_input(payload))
    assert event.context.scratchpad_dir == "/tmp/native/scratchpad"


def test_shared_output_intent_is_checked_against_the_semantic_event() -> None:
    wire_event = claude_code.parse_input(_payload("claude_code_inputs.json", "PermissionRequest"))
    event = shared.from_claude_code(wire_event)

    with pytest.raises(SharedOutputError, match="not portable"):
        shared.outputs.to_claude_code_output(
            event,
            shared.outputs.AddContext(text="This event has no portable context output."),
        )


def test_compaction_context_error_points_to_context_capable_boundary() -> None:
    wire_event = codex.parse_input(_payload("codex_inputs.json", "PostCompact"))
    event = shared.from_codex(wire_event)

    with pytest.raises(SharedOutputError) as raised:
        shared.outputs.to_codex_output(
            event,
            shared.outputs.AddContext(text="Re-ground the compacted session."),
        )

    assert str(raised.value) == (
        "AddContext is not portable for CompactionFinished (codex PostCompact); "
        "valid events: PromptSubmitted, SessionStarted, SubagentStarted, "
        "ToolCallCompleted, ToolCallProposed. Return post-compaction context from "
        "SessionStarted(source='compact') instead"
    )


def test_shared_app_handles_one_host_payload() -> None:
    app = shared.HookApp(name="test")

    @app.on(shared.events.PromptSubmitted)
    def add_context(_event: shared.events.PromptSubmitted) -> shared.outputs.Result:
        return shared.outputs.AddContext(text="Check project tests first.")

    payload = _payload("codex_inputs.json", "UserPromptSubmit")

    rendered = app.handle("codex", payload)

    assert rendered == (
        '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit",'
        '"additionalContext":"Check project tests first."}}'
    )


@pytest.mark.parametrize("source", ["startup", "resume", "clear", "compact", "fork"])
@pytest.mark.parametrize("host", ["codex", "claude"])
def test_session_start_source_reaches_shared_handler(
    source: str, host: Literal["codex", "claude"]
) -> None:
    app = shared.HookApp(name="session-source")

    @app.on(shared.events.SessionStarted)
    def add_context(event: shared.events.SessionStarted) -> shared.outputs.Result:
        return shared.outputs.AddContext(text=f"Session source: {event.source}")

    payload = _payload(FIXTURE_BY_HOST[host], "SessionStart") | {"source": source}

    rendered = app.handle(host, payload)

    assert rendered is not None
    assert json.loads(rendered) == {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": f"Session source: {source}",
        }
    }


def test_shared_permission_decisions_render_for_both_hosts() -> None:
    codex_event = shared.from_codex(
        codex.parse_input(_payload("codex_inputs.json", "PermissionRequest"))
    )
    claude_event = shared.from_claude_code(
        claude_code.parse_input(_payload("claude_code_inputs.json", "PermissionRequest"))
    )

    codex_output = shared.outputs.to_codex_output(
        codex_event,
        shared.outputs.DenyPermission(reason="Approval required by policy."),
    )
    claude_output = shared.outputs.to_claude_code_output(
        claude_event,
        shared.outputs.AllowPermission(),
    )

    assert isinstance(codex_output, codex.outputs.PermissionRequestOutput)
    assert codex_output.hook_specific_output is not None
    assert codex_output.hook_specific_output.decision.behavior == "deny"
    assert codex_output.hook_specific_output.decision.message == ("Approval required by policy.")
    assert isinstance(claude_output, claude_code.outputs.PermissionRequestOutput)
    assert claude_output.hook_specific_output is not None
    assert claude_output.hook_specific_output.decision.behavior == "allow"


def test_registration_uses_event_models_not_strings() -> None:
    app = shared.HookApp(name="test")

    with pytest.raises(ValueError, match="unsupported event model"):
        app.on(cast(Any, codex.events.UserPromptSubmitInput))
