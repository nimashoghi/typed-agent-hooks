import json
from pathlib import Path
from typing import Any, cast

import pytest

from typed_agent_hooks import claude_code, codex, shared
from typed_agent_hooks.shared.results import SharedOutputError

FIXTURES = Path(__file__).parent / "fixtures"


def _payloads(name: str) -> list[dict[str, object]]:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return data


def _payload(name: str, event_name: str) -> dict[str, object]:
    return next(item for item in _payloads(name) if item["hook_event_name"] == event_name)


def test_codex_events_have_total_shared_mappings() -> None:
    events = [
        shared.from_codex(codex.parse_input(payload)) for payload in _payloads("codex_inputs.json")
    ]

    assert {event.event_name for event in events} == set(shared.events.EVENT_NAMES)


def test_claude_only_event_is_not_coerced_into_shared_mode() -> None:
    wire_event = claude_code.parse_input(_payload("claude_code_inputs.json", "Notification"))

    assert shared.try_from_claude_code(wire_event) is None
    with pytest.raises(shared.NoSharedMappingError, match="no shared semantic mapping"):
        shared.from_claude_code(wire_event)


def test_shared_output_intent_is_checked_against_the_semantic_event() -> None:
    wire_event = claude_code.parse_input(_payload("claude_code_inputs.json", "PermissionRequest"))
    event = shared.from_claude_code(wire_event)

    with pytest.raises(SharedOutputError, match="not portable"):
        shared.outputs.to_claude_code_output(
            event,
            shared.outputs.AddContext(text="This event has no portable context output."),
        )


def test_shared_app_requires_explicit_provider_at_runtime() -> None:
    app = shared.HookApp()

    @app.on(shared.events.PromptSubmitted)
    def add_context(
        _event: shared.events.AnyEvent,
    ) -> shared.outputs.Result:
        return shared.outputs.AddContext(text="Check project tests first.")

    payload = _payload("codex_inputs.json", "UserPromptSubmit")
    # The public Provider enum is explicit; no provider auto-detection occurs.
    from typed_agent_hooks.core import Provider

    rendered = app.handle_json(Provider.CODEX, payload)

    assert rendered == (
        '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit",'
        '"additionalContext":"Check project tests first."}}'
    )


def test_shared_permission_decisions_render_for_both_providers() -> None:
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
    app = codex.HookApp()

    with pytest.raises(ValueError, match="unsupported event model"):
        app.on(cast(Any, shared.events.PromptSubmitted))
