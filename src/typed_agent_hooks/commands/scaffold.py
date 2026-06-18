"""Create minimal hook projects without embedding templates in the CLI parser."""

import re
from pathlib import Path
from typing import Literal, TypeAlias

from typed_agent_hooks import claude_code, codex
from typed_agent_hooks.shared.events import EVENT_NAMES as SHARED_EVENT_NAMES

Mode: TypeAlias = Literal["codex", "claude_code", "shared"]


def _default_events(mode: Mode) -> list[str]:
    if mode == "shared":
        return ["PromptSubmitted", "ToolCallProposed"]
    return ["UserPromptSubmit", "PreToolUse"]


def _validate_events(mode: Mode, events: list[str]) -> None:
    supported: set[str]
    if mode == "codex":
        supported = set(codex.EVENT_NAMES)
    elif mode == "claude_code":
        supported = set(claude_code.EVENT_NAMES)
    else:
        supported = set(SHARED_EVENT_NAMES)

    unknown = set(events) - supported
    if unknown:
        raise ValueError(f"unsupported {mode} events: {', '.join(sorted(unknown))}")


def _project_name(path: Path) -> str:
    raw = path.name.lstrip(".") or "agent-hooks"
    slug = re.sub(r"[^a-z0-9_-]+", "-", raw.lower()).strip("-_")
    if not slug or not slug[0].isalpha():
        slug = f"hooks-{slug}" if slug else "agent-hooks"
    return slug


def _shared_hooks_py() -> str:
    return """from __future__ import annotations

from typed_agent_hooks import shared

app = shared.HookApp()


@app.on(shared.events.PromptSubmitted)
def on_prompt(event: shared.events.PromptSubmitted) -> shared.outputs.Result:
    if "AWS_SECRET_ACCESS_KEY" in event.prompt:
        return shared.outputs.Block(reason="Remove secrets before submitting this prompt.")
    return shared.outputs.AddContext(text="Inspect project tests before editing.")


@app.on(shared.events.ToolCallProposed)
def on_tool(event: shared.events.ToolCallProposed) -> shared.outputs.Result:
    if event.tool_name != "Bash" or not isinstance(event.tool_input, dict):
        return None
    command = event.tool_input.get("command")
    if isinstance(command, str) and "rm -rf /" in command:
        return shared.outputs.DenyTool(
            reason="Refusing destructive root command.",
        )
    return None
"""


def _codex_hooks_py() -> str:
    return """from __future__ import annotations

from typed_agent_hooks import codex

app = codex.HookApp()


@app.on(codex.events.UserPromptSubmitInput)
def on_prompt(
    event: codex.events.UserPromptSubmitInput,
) -> codex.outputs.HookResult:
    if "AWS_SECRET_ACCESS_KEY" not in event.prompt:
        return None
    return codex.outputs.UserPromptSubmitOutput(
        decision="block",
        reason="Remove secrets before submitting this prompt.",
    )


@app.on(codex.events.PreToolUseInput)
def on_tool(event: codex.events.PreToolUseInput) -> codex.outputs.HookResult:
    if event.tool_name != "Bash" or not isinstance(event.tool_input, dict):
        return None
    command = event.tool_input.get("command")
    if not isinstance(command, str) or "rm -rf /" not in command:
        return None
    return codex.outputs.PreToolUseOutput(
        hook_specific_output=codex.outputs.PreToolUseDecision(
            hook_event_name="PreToolUse",
            permission_decision="deny",
            permission_decision_reason="Refusing destructive root command.",
        )
    )
"""


def _claude_hooks_py() -> str:
    return """from __future__ import annotations

from typed_agent_hooks import claude_code

app = claude_code.HookApp()


@app.on(claude_code.events.UserPromptSubmitInput)
def on_prompt(
    event: claude_code.events.UserPromptSubmitInput,
) -> claude_code.outputs.HookResult:
    if "AWS_SECRET_ACCESS_KEY" not in event.prompt:
        return None
    return claude_code.outputs.UserPromptSubmitOutput(
        decision="block",
        reason="Remove secrets before submitting this prompt.",
    )


@app.on(claude_code.events.PreToolUseInput)
def on_tool(
    event: claude_code.events.PreToolUseInput,
) -> claude_code.outputs.HookResult:
    if event.tool_name != "Bash" or not isinstance(event.tool_input, dict):
        return None
    command = event.tool_input.get("command")
    if not isinstance(command, str) or "rm -rf /" not in command:
        return None
    return claude_code.outputs.PreToolUseOutput(
        hook_specific_output=claude_code.outputs.PreToolUseSpecificOutput(
            hook_event_name="PreToolUse",
            permission_decision="deny",
            permission_decision_reason="Refusing destructive root command.",
        )
    )
"""


def _hookset_toml(name: str, mode: Mode, events: list[str]) -> str:
    lines = [f'name = "{name}"', f'mode = "{mode}"', 'app = "hooks.py:app"', ""]
    for event in events:
        lines.extend(["[[hooks]]", f'event = "{event}"', "timeout = 30"])
        lines.append(f'status_message = "Running {event} policy"')
        if mode == "shared" and event == "ToolCallProposed":
            lines.extend(
                [
                    "[hooks.codex]",
                    'matcher = "Bash"',
                    "[hooks.claude_code]",
                    'matcher = "Bash"',
                ]
            )
        elif mode != "shared" and event == "PreToolUse":
            lines.append('matcher = "Bash"')
        lines.append("")
    return "\n".join(lines)


def _readme(mode: Mode) -> str:
    cli_mode = mode.replace("_", "-")
    provider = "claude-code" if mode == "claude_code" else "codex"
    provider_flag = f" --provider {provider}" if mode == "shared" else ""
    return f"""# Hook project

Mode: `{cli_mode}`

```bash
typed-agent-hooks check hookset.toml
typed-agent-hooks render hookset.toml --provider all --pretty
typed-agent-hooks install hookset.toml --provider all --scope project
```

Run a captured payload:

```bash
typed-agent-hooks run {cli_mode} hooks.py:app{provider_flag} < payload.json
```
"""


def create_project(
    path: str | Path,
    *,
    mode: Mode,
    events: list[str] | None = None,
    force: bool = False,
) -> Path:
    """Create a minimal hook project and return its directory."""

    target = Path(path).expanduser()
    if target.exists() and any(target.iterdir()) and not force:
        raise FileExistsError(f"{target} is not empty; pass --force to overwrite templates")

    selected_events = events or _default_events(mode)
    _validate_events(mode, selected_events)
    target.mkdir(parents=True, exist_ok=True)

    if mode == "shared":
        hooks_py = _shared_hooks_py()
    elif mode == "codex":
        hooks_py = _codex_hooks_py()
    else:
        hooks_py = _claude_hooks_py()

    (target / "hooks.py").write_text(hooks_py, encoding="utf-8")
    (target / "hookset.toml").write_text(
        _hookset_toml(_project_name(target), mode, selected_events),
        encoding="utf-8",
    )
    (target / "README.md").write_text(_readme(mode), encoding="utf-8")
    return target
