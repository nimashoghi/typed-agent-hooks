"""Cold-process import boundaries for latency-sensitive hook execution."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from typing import cast


def _loaded_modules(program: str) -> set[str]:
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(program)],
        check=True,
        capture_output=True,
        text=True,
    )
    decoded = json.loads(completed.stdout)
    assert isinstance(decoded, list)
    assert all(isinstance(item, str) for item in decoded)
    return set(cast(list[str], decoded))


def test_shared_import_does_not_load_provider_or_collection_modules() -> None:
    loaded = _loaded_modules(
        """
        import json
        import sys
        from typed_agent_hooks import shared

        print(json.dumps(sorted(sys.modules)))
        """
    )

    assert "typed_agent_hooks.shared" in loaded
    assert "typed_agent_hooks.codex" not in loaded
    assert "typed_agent_hooks.claude_code" not in loaded
    assert "typed_agent_hooks.collection" not in loaded
    assert "cyclopts" not in loaded


def test_codex_dispatch_does_not_load_claude_code() -> None:
    loaded = _loaded_modules(
        """
        import json
        import sys
        from typed_agent_hooks import shared
        from typed_agent_hooks.core import Provider

        app = shared.HookApp(name="probe", providers=("codex",))

        @app.on(shared.events.PromptSubmitted)
        def prompt_submitted(event):
            return None

        app.handle_json(
            Provider.CODEX,
            {
                "session_id": "session",
                "transcript_path": None,
                "cwd": ".",
                "hook_event_name": "UserPromptSubmit",
                "model": "gpt-5",
                "permission_mode": "default",
                "turn_id": "turn",
                "prompt": "hello",
            },
        )
        print(json.dumps(sorted(sys.modules)))
        """
    )

    assert "typed_agent_hooks.codex" in loaded
    assert "typed_agent_hooks.claude_code" not in loaded
