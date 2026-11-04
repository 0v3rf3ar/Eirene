"""Command line entry point."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from . import __version__

# Piped input larger than this is refused rather than silently cut.
STDIN_LIMIT = 4 * 1024 * 1024
# How long to wait for piped input to start before treating stdin as unused.
STDIN_WAIT = 3.0


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a whole number, got {text!r}") from None
    if value <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return value


def _name_list(text: str) -> list[str]:
    from .scheduling.base import parse_names
    return parse_names(text)


def _tool_list(text: str) -> list[str]:
    from .core.errors import SchedulerError
    from .scheduling.base import parse_tools
    try:
        return parse_tools(text)
    except SchedulerError as exc:
        raise argparse.ArgumentTypeError(exc.user_message()) from None


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
    sessions = parser.add_mutually_exclusive_group()
    sessions.add_argument("--resume", metavar="UUID", nargs="?", const="", default=None,
                        help="continue a saved session; omit the id to list them")
    sessions.add_argument("--continue", dest="continue_session", action="store_true",
                          help="continue the most recent session for this workspace without a picker")
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
    parser.add_argument("--mode", choices=("auto", "manual", "accept", "plan"), default="auto",
                        help="permission mode for -p (default: auto)")
    run = parser.add_argument_group("headless run limits (-p)")
    run.add_argument("--tools", type=_tool_list, metavar="LIST",
                     help="tools the run may use, e.g. 'edit, commands' or 'all': read, edit, "
                          "commands, web, mcp, agents (read is always allowed; default: all)")
    run.add_argument("--mcp", type=_name_list, metavar="SERVERS",
                     help="MCP servers the run may call without approval: names, 'all' "
                          "(every server enabled in /mcp) or 'none' (default)")
    run.add_argument("--skills", type=_name_list, metavar="NAMES",
                     help="skills the run may load: names, 'all' or 'none' "
                          "(default: the skills enabled in /skills)")
    run.add_argument("--access", choices=("sandboxed", "full-access"),
                     help="sandbox level for this run only (default: sandboxed)")
    run.add_argument("--timeout", type=_positive_int, metavar="SECONDS",
                     help="stop the run after this many seconds (default: 3600)")
    run.add_argument("--max-steps", type=_positive_int, metavar="N",
                     help="stop after N tool rounds in the turn")
    run.add_argument("--max-tokens", type=_positive_int, metavar="N",
                     help="stop once input plus output tokens reach N (checked after each model reply)")
    run.add_argument("-q", "--quiet", action="store_true",
                     help="print only the answer and errors; hide tool activity on stderr")
    run.add_argument("--stream-json", action="store_true",
                     help="write one JSON event per line to stdout, ending with the result")
    parser.add_argument("--doctor", action="store_true",
                        help="print read-only installation diagnostics and exit")
    parser.add_argument("--json", action="store_true",
                        help="use JSON output for diagnostics or headless runs")
    parser.add_argument("--no-color", action="store_true",
                        help="disable terminal colour for this run")
    parser.add_argument("--reduce-motion", action="store_true",
                        help="disable animated terminal title indicators")
    parser.add_argument("--debug", action="store_true",
                        help="log at debug level and show where unexpected errors happen")
    parser.add_argument("--permission-proxy", metavar="PORT:TOKEN",
                        help=argparse.SUPPRESS)
    parser.add_argument("--attachment-reader", metavar="SESSION", help=argparse.SUPPRESS)
    parser.add_argument("--mcp-proxy", metavar="NAME", help=argparse.SUPPRESS)
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
    except Exception as exc:  # noqa: BLE001 - failed before the interface could report it
        from .core import crash
        report = crash.record(exc, where="startup", fatal=True)
        sys.stderr.write(f"eirene could not start: {crash.summary(exc)}\n")
        if report is not None:
            sys.stderr.write(f"crash report: {report}\n")
        return 1


def read_stdin(prompt: str) -> str | None:
    """The prompt with piped input added; None when the input is too large.

    ``-p -`` takes the whole prompt from stdin. Otherwise piped input is added
    after the prompt, unless nothing arrives within STDIN_WAIT seconds: a caller
    that leaves an open, unused pipe must not hang the run.
    """
    stream = sys.stdin
    if stream is None or prompt != "-" and (prompt.startswith("/") or _isatty(stream)):
        return prompt
    import threading
    chunks: list[bytes] = []
    state = {"size": 0, "over": False}
    began, done = threading.Event(), threading.Event()

    def pump() -> None:
        source = getattr(stream, "buffer", None)
        try:
            while True:
                chunk = source.read1(65536) if source else stream.read(65536).encode()
                began.set()
                if not chunk:
                    break
                state["size"] += len(chunk)
                if state["size"] > STDIN_LIMIT:
                    state["over"] = True
                    break
                chunks.append(chunk)
        except Exception:  # noqa: BLE001 - an unreadable stdin is treated as empty
            pass
        finally:
            began.set()
            done.set()

    threading.Thread(target=pump, name="eirene-stdin", daemon=True).start()
    if prompt != "-" and not began.wait(STDIN_WAIT):
        return prompt
    done.wait()
    if state["over"]:
        return None
    data = b"".join(chunks).decode("utf-8", errors="replace")
    if prompt == "-":
        return data.strip()
    if not data.strip():
        return prompt
    return f"{prompt}\n\n<stdin>\n{data.rstrip()}\n</stdin>"


def _isatty(stream) -> bool:
    try:
        return stream.isatty()
    except (OSError, ValueError):
        return False


RUN_FLAGS = ("tools", "mcp", "skills", "access", "timeout", "max_steps", "max_tokens", "quiet", "stream_json")


def main(argv: list[str] | None = None) -> int:
    # A legacy Windows console code page cannot encode every model character;
    # replace them rather than abort a headless run mid-answer.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)

    if args.mcp_proxy:
        from .core.mcp_proxy import proxy_main
        return proxy_main(args.mcp_proxy)
    if args.permission_proxy:
        from .providers.permission_proxy import proxy_main
        port, _, token = args.permission_proxy.partition(":")
        return proxy_main(int(port), token)
    if args.attachment_reader:
        from .providers.attachment_reader import reader_main
        return reader_main(args.attachment_reader)

    if args.no_color:
        os.environ["NO_COLOR"] = "1"
    if args.reduce_motion:
        os.environ["EIRENE_REDUCE_MOTION"] = "1"
    if args.debug:
        os.environ["EIRENE_DEBUG"] = "1"

    if args.doctor:
        from .core.config import Config
        from .core.diagnostics import collect, render
        report = collect(Config.load())
        sys.stdout.write(render(report, json_output=args.json) + "\n")
        return 0 if report["ok"] else 1

    discovering = args.list_providers or args.configured_providers or args.list_models is not None
    used = [name for name in RUN_FLAGS if getattr(args, name) not in (None, False)]
    if used and args.prompt is None and not discovering:
        flags = ", ".join("--" + name.replace("_", "-") for name in used)
        sys.stderr.write(f"{flags} only apply to headless runs with -p\n")
        return 2
    if args.stream_json and args.json:
        sys.stderr.write("use either --json or --stream-json, not both\n")
        return 2

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

    if args.continue_session:
        from .core.session import list_sessions

        found = list_sessions(limit=1, sandbox=sandbox)
        if not found:
            sys.stdout.write(f"no saved sessions for {sandbox}\n")
            return 0
        args.resume = found[0]["id"]

    text = args.prompt
    if text is not None and not discovering:
        text = read_stdin(text)
        if text is None:
            sys.stderr.write(f"piped input is larger than {STDIN_LIMIT // (1024 * 1024)} MB\n")
            return 2
        if not text.strip():
            sys.stderr.write("the prompt is empty\n")
            return 2
    if args.list_providers:
        text = "/providers"
    elif args.configured_providers:
        text = "/providers configured"
    elif args.list_models is not None:
        text = "/models" + (f" {args.list_models}" if args.list_models else "")
    if text is not None:
        from .headless import TASK_TIMEOUT, access_note, run_prompt
        instructions = ""
        if args.tools is not None:
            instructions = access_note(args.access or "sandboxed", args.tools,
                                       mcp_servers=args.mcp)
        return run_prompt(text, sandbox, provider=args.provider or "",
                          model=args.model or "", mode=args.mode,
                          json_output=args.json, choices=args.choice,
                          inputs=args.command_input, quiet=args.quiet,
                          stream_json=args.stream_json,
                          task_timeout=args.timeout or TASK_TIMEOUT,
                          permissions=args.access or "", tool_groups=args.tools,
                          step_limit=args.max_steps, token_limit=args.max_tokens,
                          instructions=instructions, mcp_servers=args.mcp,
                          skills=args.skills, strict=True)

    if not sys.stdout.isatty():
        sys.stderr.write("eirene needs a terminal; use -p for one-shot runs\n")
        return 2

    return open_session(sandbox, args.resume or "")


if __name__ == "__main__":
    raise SystemExit(main())
