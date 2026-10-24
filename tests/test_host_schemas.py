import importlib
import json
import pkgutil
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

import typed_agent_hooks
from typed_agent_hooks import claude_code, codex
from typed_agent_hooks.core import InputModel, StrictModel

FIXTURES = Path(__file__).parent / "fixtures"


def _payloads(name: str) -> list[dict[str, object]]:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert all(isinstance(item, dict) for item in data)
    return data


def test_all_codex_fixture_events_parse_strictly() -> None:
    payloads = _payloads("codex_inputs.json")

    parsed = [codex.parse_input(payload) for payload in payloads]

    assert {event.hook_event_name for event in parsed} == set(codex.INPUT_TYPES)


def test_claude_code_fixture_events_parse_strictly_or_are_unsupported() -> None:
    payloads = _payloads("claude_code_inputs.json")
    modeled = [item for item in payloads if item["hook_event_name"] in claude_code.INPUT_TYPES]
    host_only = [item for item in payloads if item not in modeled]

    parsed = [claude_code.parse_input(payload) for payload in modeled]

    assert {event.hook_event_name for event in parsed} == set(claude_code.INPUT_TYPES)
    # Events with no shared equivalent, such as Notification, are not modeled.
    assert len(host_only) == 19
    for payload in host_only:
        with pytest.raises(ValueError, match="unsupported Claude Code hook event"):
            claude_code.parse_input(payload)


@pytest.mark.parametrize(
    ("parser", "fixture_name"),
    [
        (codex.parse_input, "codex_inputs.json"),
        (claude_code.parse_input, "claude_code_inputs.json"),
    ],
)
def test_host_inputs_ignore_unknown_fields(parser, fixture_name: str) -> None:
    # Tolerant readers: a host adding a payload field must never turn into
    # a dropped event. Claude Code's prompt_id addition proved forbid fatal.
    payload = _payloads(fixture_name)[0] | {"unexpected": True}

    parsed = parser(payload)

    assert not hasattr(parsed, "unexpected")


def test_host_inputs_still_reject_declared_field_type_drift() -> None:
    payload = next(
        item
        for item in _payloads("claude_code_inputs.json")
        if item["hook_event_name"] == "PostToolUse"
    ) | {"tool_use_id": 7}

    with pytest.raises(ValidationError):
        claude_code.parse_input(payload)


@pytest.mark.parametrize("source", ["unknown", 7, None])
def test_claude_session_start_rejects_invalid_sources(source: object) -> None:
    payload = _payloads("claude_code_inputs.json")[0] | {"source": source}

    with pytest.raises(ValidationError, match="SessionStartInput\nsource"):
        claude_code.parse_input(payload)


def test_models_accept_python_names_and_emit_host_aliases() -> None:
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


@pytest.mark.parametrize("parser", [codex.parse_input, claude_code.parse_input])
@pytest.mark.parametrize("name", ["Unknown", 7, None])
def test_unknown_hook_event_names_are_rejected(parser, name: object) -> None:
    with pytest.raises(ValueError, match="hook event"):
        parser({"hook_event_name": name})


def test_every_deferred_model_schema_builds() -> None:
    # Models defer their schemas to first use. Build each one here, so that a
    # broken schema fails this test and not a hook run.
    for module in pkgutil.walk_packages(typed_agent_hooks.__path__, "typed_agent_hooks."):
        importlib.import_module(module.name)
    pending: list[type[BaseModel]] = [InputModel, StrictModel]
    while pending:
        model = pending.pop()
        pending.extend(model.__subclasses__())
        assert model.model_rebuild(force=True) is True, model
