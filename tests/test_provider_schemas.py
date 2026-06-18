import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from typed_agent_hooks import claude_code, codex

FIXTURES = Path(__file__).parent / "fixtures"


def _payloads(name: str) -> list[dict[str, object]]:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert all(isinstance(item, dict) for item in data)
    return data


def test_all_codex_fixture_events_parse_strictly() -> None:
    payloads = _payloads("codex_inputs.json")

    parsed = [codex.parse_input(payload) for payload in payloads]

    assert {event.hook_event_name for event in parsed} == set(codex.EVENT_NAMES)


def test_all_claude_code_fixture_events_parse_strictly() -> None:
    payloads = _payloads("claude_code_inputs.json")

    parsed = [claude_code.parse_input(payload) for payload in payloads]

    assert {event.hook_event_name for event in parsed} == set(claude_code.EVENT_NAMES)


@pytest.mark.parametrize(
    ("parser", "fixture_name"),
    [
        (codex.parse_input, "codex_inputs.json"),
        (claude_code.parse_input, "claude_code_inputs.json"),
    ],
)
def test_provider_inputs_reject_unknown_fields(parser, fixture_name: str) -> None:
    payload = _payloads(fixture_name)[0] | {"unexpected": True}

    with pytest.raises(ValidationError, match="unexpected"):
        parser(payload)


def test_codex_app_rejects_an_output_for_the_wrong_event() -> None:
    app = codex.HookApp()

    @app.on(codex.events.UserPromptSubmitInput)
    def wrong_output(
        _event: codex.events.AnyInput,
    ) -> codex.outputs.HookResult:
        return codex.outputs.PreToolUseOutput()

    payload = next(
        payload
        for payload in _payloads("codex_inputs.json")
        if payload["hook_event_name"] == "UserPromptSubmit"
    )

    with pytest.raises(TypeError, match="expected UserPromptSubmitOutput"):
        app.handle_json(payload)


def test_provider_config_rejects_matchers_for_events_that_ignore_them() -> None:
    codex_group = codex.config.HookGroup(
        matcher="anything",
        hooks=[codex.config.CommandHook(command="python hook.py")],
    )
    with pytest.raises(ValidationError, match="ignores matchers"):
        codex.config.HooksFile(hooks={"UserPromptSubmit": [codex_group]})

    claude_group = claude_code.config.HookGroup(
        matcher="anything",
        hooks=[claude_code.config.CommandHook(command="python", args=["hook.py"])],
    )
    with pytest.raises(ValidationError, match="ignores matchers"):
        claude_code.config.SettingsHooks(hooks={"UserPromptSubmit": [claude_group]})


def test_models_accept_python_names_and_emit_provider_aliases() -> None:
    output = codex.outputs.UserPromptSubmitOutput(
        hook_specific_output=codex.outputs.UserPromptSubmitSpecificOutput(
            hook_event_name="UserPromptSubmit",
            additional_context="Review tests before editing.",
        )
    )

    assert output.model_dump(by_alias=True, exclude_none=True) == {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "Review tests before editing.",
        }
    }

    command = claude_code.config.CommandHook(
        command="python",
        async_=True,
        condition="Bash(*)",
    )

    assert command.model_dump(by_alias=True, exclude_none=True) == {
        "type": "command",
        "command": "python",
        "async": True,
        "if": "Bash(*)",
    }
