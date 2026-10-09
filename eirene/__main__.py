"""Command line entry point."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eirene",
        description="Terminal AI agent for coding, automation and deployment.")
    parser.add_argument("-p", "--prompt", metavar="TEXT",
                        help="run one prompt without the interface and exit")
    parser.add_argument("--task", metavar="ID",
                        help="run a scheduled task by id (used by the scheduler)")
    parser.add_argument("-C", "--directory", metavar="DIR", default=".",
                        help="sandbox directory (default: the current one)")
    parser.add_argument("--resume", metavar="UUID", nargs="?", const="", default=None,
                        help="continue a saved session; omit the id to list them")
    parser.add_argument("--provider", metavar="NAME", help="override the provider")
    parser.add_argument("--model", metavar="NAME", help="override the model")
    discovery = parser.add_mutually_exclusive_group()
    discovery.add_argument("--list-providers", action="store_true",
                           help="list available providers without the interface")
    discovery.add_argument("--configured-providers", action="store_true",
                           help="list saved provider connections without credentials")
    discovery.add_argument("--list-models", metavar="PROVIDER", nargs="?", const="",
                           help="list models for a provider (default: active provider)")
    parser.add_argument("--choice", action="append", default=[], metavar="KEY",
                        help="supply a slash-command choice; repeat in prompt order")
    parser.add_argument("--command-input", action="append", default=[], metavar="TEXT",
                        help="supply slash-command text input; repeat in prompt order")
    parser.add_argument("--mode", choices=("auto", "manual", "plan"), default="auto",
                        help="permission mode for -p (default: auto)")
    parser.add_argument("--doctor", action="store_true",
                        help="print read-only installation diagnostics and exit")
    parser.add_argument("--json", action="store_true",
                        help="use JSON output for diagnostics or headless runs")
    parser.add_argument("--no-color", action="store_true",
                        help="disable terminal colour for this run")
    parser.add_argument("--reduce-motion", action="store_true",
                        help="disable animated terminal title indicators")
    parser.add_argument("--permission-proxy", metavar="PORT:TOKEN",
                        help=argparse.SUPPRESS)
    parser.add_argument("-v", "--version", action="version",
                        version=f"eirene {__version__}")
    return parser


def print_sessions(sandbox: Path, found: list) -> int:
    """Plain list, for when there is no terminal."""
    sys.stdout.write(f"sessions for {sandbox}:\n")
    for info in found:
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(info["mtime"]))
        turns = info["turns"]
        plural = "" if turns == 1 else "s"
        sys.stdout.write(f"  {info['name']}\n")
        sys.stdout.write(f"    {info['id']}  {stamp}  {turns} turn{plural}\n")
    sys.stdout.write("\nresume one with: eirene --resume <uuid>\n")
    return 0


def pick_session(sandbox: Path) -> int:
    """Choose a saved session, then open it."""
    from .core.session import list_sessions

    found = list_sessions(sandbox=sandbox)
    if not found:
        sys.stdout.write(f"no saved sessions for {sandbox}\n")
        return 0
    if not sys.stdout.isatty():
        return print_sessions(sandbox, found)

    from .ui.sessions import choose_session
    chosen = choose_session(found, sandbox)
    if not chosen:
        return 0
    return open_session(sandbox, chosen)


def open_session(sandbox: Path, resume: str) -> int:
    """Start the interface on one session."""
    from .app import run
    from .core.errors import SessionError
    try:
        return run(sandbox, resume)
    except SessionError as exc:
        sys.stderr.write(f"{exc.user_message()}\n")
        return 2
    except KeyboardInterrupt:
        return 130


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.permission_proxy:
        from .providers.permission_proxy import proxy_main
        port, _, token = args.permission_proxy.partition(":")
        return proxy_main(int(port), token)

    if args.no_color:
        os.environ["NO_COLOR"] = "1"
    if args.reduce_motion:
        os.environ["EIRENE_REDUCE_MOTION"] = "1"

    if args.doctor:
        from .core.config import Config
        from .core.diagnostics import collect, render
        report = collect(Config.load())
        sys.stdout.write(render(report, json_output=args.json) + "\n")
        return 0 if report["ok"] else 1

    if args.task:
        from .headless import run_task
        return run_task(args.task, json_output=args.json)

    try:
        sandbox = Path(args.directory).expanduser().resolve(strict=True)
    except (OSError, FileNotFoundError):
        sys.stderr.write(f"no such directory: {args.directory}\n")
        return 2
    if not sandbox.is_dir():
        sys.stderr.write(f"not a directory: {sandbox}\n")
        return 2

    if args.resume == "":
        return pick_session(sandbox)

    text = args.prompt
    if args.list_providers:
        text = "/providers"
    elif args.configured_providers:
        text = "/providers configured"
    elif args.list_models is not None:
        text = "/models" + (f" {args.list_models}" if args.list_models else "")
    if text is not None:
        from .headless import run_prompt
        return run_prompt(text, sandbox, provider=args.provider or "",
                          model=args.model or "", mode=args.mode,
                          json_output=args.json, choices=args.choice,
                          inputs=args.command_input)

    if not sys.stdout.isatty():
        sys.stderr.write("eirene needs a terminal; use -p for one-shot runs\n")
        return 2

    return open_session(sandbox, args.resume or "")


if __name__ == "__main__":
    raise SystemExit(main())
