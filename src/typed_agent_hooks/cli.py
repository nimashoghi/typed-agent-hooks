"""Command-line interface for developing and managing typed hooksets."""

import argparse
import json
import logging
import sys

from pydantic import ValidationError

from typed_agent_hooks.commands import hookset as hookset_commands
from typed_agent_hooks.commands.runtime import input_schema, run_hook, validate_input
from typed_agent_hooks.commands.scaffold import create_project
from typed_agent_hooks.core import Provider
from typed_agent_hooks.fastmcp.shim import add_forward_arguments, run_from_args
from typed_agent_hooks.hooksets import ConfigChange

log = logging.getLogger(__name__)


def _normalize_mode(value: str) -> str:
    normalized = value.replace("-", "_")
    if normalized not in {"codex", "claude_code", "shared"}:
        raise argparse.ArgumentTypeError("mode must be codex, claude-code, or shared")
    return normalized


def _normalize_provider(value: str) -> str:
    normalized = value.replace("-", "_")
    if normalized not in {"codex", "claude_code"}:
        raise argparse.ArgumentTypeError("provider must be codex or claude-code")
    return normalized


def _normalize_provider_selection(value: str) -> str:
    return "all" if value == "all" else _normalize_provider(value)


def _read_stdin() -> str:
    data = sys.stdin.read()
    if not data.strip():
        raise ValueError("expected hook JSON on stdin")
    return data


def _cmd_init(args: argparse.Namespace) -> int:
    target = create_project(
        args.path,
        mode=args.mode,
        events=args.event,
        force=args.force,
    )
    print(target)
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    report = hookset_commands.check(args.hookset, python_executable=args.python_executable)
    print(f"ok: {report.name} ({report.mode})")
    print(f"providers: {', '.join(report.providers)}")
    print(f"events: {', '.join(report.configured_events)}")
    if report.extra_handlers:
        print(f"extra handlers: {', '.join(report.extra_handlers)}")
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    configs = hookset_commands.render(
        args.hookset,
        provider=args.provider,
        python_executable=args.python_executable,
    )
    output: object = configs if args.provider == "all" else next(iter(configs.values()))
    print(json.dumps(output, indent=2 if args.pretty else None, ensure_ascii=False))
    return 0


def _print_changes(changes: dict[str, ConfigChange]) -> None:
    for provider_name, raw_change in changes.items():
        change = raw_change
        status = "updated" if change.changed else "unchanged"
        print(f"{provider_name}: {status} {change.path}")


def _cmd_install(args: argparse.Namespace) -> int:
    changes = hookset_commands.install(
        args.hookset,
        provider=args.provider,
        scope=args.scope,
        project_root=args.project_root,
        target_path=args.path,
        python_executable=args.python_executable,
    )
    _print_changes(changes)
    return 0


def _cmd_uninstall(args: argparse.Namespace) -> int:
    changes = hookset_commands.uninstall(
        args.hookset,
        provider=args.provider,
        scope=args.scope,
        project_root=args.project_root,
        target_path=args.path,
    )
    _print_changes(changes)
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    provider = Provider(args.provider) if args.provider is not None else None
    output = run_hook(
        args.mode,
        args.app,
        _read_stdin(),
        provider=provider,
        base_dir=args.base_dir,
    )
    if output is not None:
        print(output)
    return 0


def _cmd_forward(args: argparse.Namespace) -> int:
    # The shim is fail-open and never raises (returns 0 even when no server is
    # running), so it deliberately does NOT ride main()'s except-tuple (-> 1).
    return run_from_args(args)


def _cmd_validate(args: argparse.Namespace) -> int:
    event = validate_input(
        Provider(args.provider),
        _read_stdin(),
        shared_mode=args.shared,
    )
    print(event.model_dump_json(by_alias=True, indent=2))
    return 0


def _cmd_schema(args: argparse.Namespace) -> int:
    schema = input_schema(args.mode)
    print(json.dumps(schema, indent=2 if args.pretty else None, ensure_ascii=False))
    return 0


def _add_provider_selection(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--provider",
        type=_normalize_provider_selection,
        choices=["codex", "claude_code", "all"],
        default="all",
    )


def _add_install_location(parser: argparse.ArgumentParser) -> None:
    _add_provider_selection(parser)
    parser.add_argument("--scope", choices=["project", "user"], default="project")
    parser.add_argument("--project-root", default=".")
    parser.add_argument(
        "--path",
        default=None,
        help="explicit config path; requires exactly one provider",
    )


def _add_run_parser(
    parent: argparse._SubParsersAction,
    mode: str,
) -> None:
    cli_mode = mode.replace("_", "-")
    parser = parent.add_parser(cli_mode)
    parser.add_argument("app", help="module:object or path.py:object")
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--hookset-name", help=argparse.SUPPRESS)
    if mode == "shared":
        parser.add_argument(
            "--provider",
            type=_normalize_provider,
            choices=["codex", "claude_code"],
            required=True,
        )
    else:
        parser.set_defaults(provider=None)
    parser.set_defaults(handler=_cmd_run, mode=mode)


def build_parser() -> argparse.ArgumentParser:
    """Build the complete CLI parser."""

    parser = argparse.ArgumentParser(prog="typed-agent-hooks")
    parser.add_argument("--debug", action="store_true", help="show full tracebacks")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="create hooks.py and hookset.toml")
    init.add_argument("path", nargs="?", default=".agent-hooks")
    init.add_argument(
        "--mode",
        type=_normalize_mode,
        choices=["codex", "claude_code", "shared"],
        default="shared",
    )
    init.add_argument("--event", action="append")
    init.add_argument("--force", action="store_true")
    init.set_defaults(handler=_cmd_init)

    check = commands.add_parser("check", help="validate a hookset and imported app")
    check.add_argument("hookset")
    check.add_argument("--python", dest="python_executable", default=None)
    check.set_defaults(handler=_cmd_check)

    render = commands.add_parser("render", help="render provider-native config")
    render.add_argument("hookset")
    _add_provider_selection(render)
    render.add_argument("--python", dest="python_executable", default=None)
    render.add_argument("--pretty", action="store_true")
    render.set_defaults(handler=_cmd_render)

    install = commands.add_parser("install", help="check and install a managed hookset")
    install.add_argument("hookset")
    _add_install_location(install)
    install.add_argument("--python", dest="python_executable", default=None)
    install.set_defaults(handler=_cmd_install)

    uninstall = commands.add_parser("uninstall", help="remove a managed hookset")
    uninstall.add_argument("hookset")
    _add_install_location(uninstall)
    uninstall.set_defaults(handler=_cmd_uninstall)

    run = commands.add_parser("run", help="run one hook payload on stdin")
    run_modes = run.add_subparsers(dest="mode", required=True)
    for mode in ("codex", "claude_code", "shared"):
        _add_run_parser(run_modes, mode)

    forward = commands.add_parser(
        "forward", help="forward one hook payload to a running fastmcp bridge"
    )
    add_forward_arguments(forward)
    forward.set_defaults(handler=_cmd_forward)

    validate = commands.add_parser("validate", help="validate one hook payload")
    validate.add_argument(
        "provider",
        type=_normalize_provider,
        choices=["codex", "claude_code"],
    )
    validate.add_argument("--shared", action="store_true")
    validate.set_defaults(handler=_cmd_validate)

    schema = commands.add_parser("schema", help="print input JSON Schema")
    schema.add_argument(
        "mode",
        type=_normalize_mode,
        choices=["codex", "claude_code", "shared"],
    )
    schema.add_argument("--pretty", action="store_true")
    schema.set_defaults(handler=_cmd_schema)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface."""

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (
        ValidationError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
        OSError,
        ImportError,
        AttributeError,
    ) as exc:
        if args.debug:
            raise
        log.error("%s", exc)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
