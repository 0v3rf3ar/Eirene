"""/schedule"""

from __future__ import annotations

import asyncio
import getpass
import re
from pathlib import Path

from rich.text import Text

from ..core.errors import CommandError, SchedulerError
from ..scheduling import backend
from ..scheduling.base import Task, load_tasks, new_id, parse_schedule, save_tasks
from ..ui import art
from ..ui.chat import Block
from . import register
from .routine_options import (Cancelled as _Cancelled, choice as _choice, pick_mcp, pick_model,
                              pick_skills, pick_tools, text as _text, with_mcp)

EXAMPLES = [("every 30m", "every 30m", "twice an hour"),
            ("hourly", "hourly", "on the hour"),
            ("daily at 09:00", "daily at 09:00", "every morning"),
            ("mon at 18:30", "mon at 18:30", "once a week"),
            ("at startup", "at startup", "when you log in")]


@register("schedule", "schedule a routine with the system scheduler",
          "/schedule [prompt]")
async def run(app, args: str) -> None:
    engine = backend()
    if not engine.available:
        raise CommandError("this platform has no scheduler backend")
    try:
        built = await _build(app, engine, args.strip())
    except _Cancelled:
        app.say("cancelled")
        return
    if built is None:
        return
    task, password = built

    installed = False
    try:
        # systemctl, launchctl and PowerShell can each take seconds; keep the UI live.
        note = await asyncio.to_thread(engine.install, task, password)
        installed = True
        tasks = load_tasks()
        tasks.append(task)
        save_tasks(tasks)
    except SchedulerError as exc:
        if installed:
            try:
                await asyncio.to_thread(engine.remove, task)
            except SchedulerError:
                pass
        raise CommandError(exc.user_message()) from exc
    app.say(f"{art.icon('ok')} {note} - runs {task.schedule.describe()}; "
            "review it with /routines")
    for warning in await asyncio.to_thread(engine.warnings, task):
        app.say(warning, "warn")


async def _build(app, engine, prompt: str) -> Task | None:
    step = _Steps()

    # 1 · what to do
    if not prompt:
        prompt = await _text(app, step("what should the routine do?"))
    if len(prompt) > 4000:
        raise CommandError("that prompt is too long for a scheduled task")

    # 2 · name
    name = _clean_name(await _text(app, step("short name for the routine")))

    # 3 · work directory
    here = Path(app.sandbox.root)
    where = await _choice(app, step("work directory"), [
        ("here", "this project", str(here)),
        ("other", "another folder…", "type a path"),
    ])
    folder = here
    if where == "other":
        raw = await _text(app, step("folder to work in (absolute or ~ path)"))
        folder = Path(raw).expanduser()
        if not folder.is_absolute():
            folder = here / folder
        folder = folder.resolve()
        if not folder.is_dir():
            raise CommandError(f"{folder} is not a folder")

    # 4 · in place or isolated
    from ..scheduling.worktree import repository_root
    workspace = "project"
    if repository_root(folder) is not None:
        workspace = await _choice(app, step("how should it work there?"), [
            ("worktree", "isolated git copy",
             "fresh checkout each run; edits kept aside for review"),
            ("project", "directly in the folder", "changes land in your working tree"),
        ])

    # 5 · model
    provider, model = await pick_model(app, step("which model should it use?"))

    # 6 · access level
    access = await _choice(app, step("access level"), [
        ("sandboxed", "sandboxed (recommended)",
         "workspace only; commands have no network; nothing outside is reachable"),
        ("full-access", "full access",
         "host files, network and commands without isolation"),
    ])

    # 7 · tools, MCP servers and skills
    tools = await pick_tools(app, step("allowed tools"))
    servers = await pick_mcp(app, step("MCP servers it may use")) or []
    tools = with_mcp(tools, servers)
    _, skills = await pick_skills(app, step("skills it may load"))

    # 8 · frequency
    picked = await _choice(app, step("how often?"), EXAMPLES + [("custom", "custom…", "")])
    if picked == "custom":
        picked = await _text(app, step("schedule, e.g. 'every 45m' or 'daily at 07:15'"))
    schedule = parse_schedule(picked)
    engine.validate(schedule)

    # 9 · signed out (only where the scheduler can do it)
    signed_out, logon, password = await _signed_out(app, engine, step)

    task = Task(id=new_id(), name=name, prompt=prompt, cwd=str(folder),
                schedule=schedule, provider=provider, model=model, access=access,
                tools=tools, mcp_servers=servers, skills=skills, workspace=workspace, run_signed_out=signed_out, signed_out_logon=logon)

    keyring = app.config.get("credential_store", "file") == "keyring"
    await app.push(Block(_summary(task, show_signed_out=engine.supports_signed_out,
                                  keyring=keyring)))
    confirm = await app.ask_choice(
        f"create '{name}'?",
        [("yes", "yes, install it", engine.name), ("no", "no", "")])
    if confirm != "yes":
        raise _Cancelled
    return task, password


async def _signed_out(app, engine, step) -> tuple[bool, str, str | None]:
    """Ask whether to keep running while signed out; returns (yes, logon, password)."""
    if not engine.supports_signed_out:
        return False, "", None
    mode, problem = await asyncio.to_thread(engine.signed_out_mode)
    if not mode:
        app.say(f"runs only while signed in: {problem}", "warn")
        return False, "", None
    hint = ("no password needed (Eirene is running as administrator)" if mode == "s4u"
            else "asks for your Windows password once; Windows keeps it, Eirene does not")
    choice = await _choice(app, step("while you are signed out?"), [
        ("no", "only while signed in", "runs that fall while signed out are skipped"),
        ("yes", "also while signed out", hint),
    ])
    if choice != "yes":
        return False, "", None
    if mode == "s4u":
        return True, "s4u", None
    user = getpass.getuser()
    secret = await app.ask_text(step(f"Windows password for {user} "
                                     "(handed to Windows, never saved by Eirene)"),
                                secret=True)
    if not secret:
        app.say("no password given; the routine will run only while signed in", "warn")
        return False, "", None
    app.say("checking with Windows (a short test run)…")
    problem = await asyncio.to_thread(engine.verify_password, secret)
    if problem:
        app.say(f"runs only while signed in: {problem}", "warn")
        return False, "", None
    return True, "password", secret


def _summary(task: Task, *, show_signed_out: bool = False, keyring: bool = False) -> Text:
    body = Text()
    body.append(f"{art.icon('task')} new routine: {task.name}\n", style="bold")
    rows = [("does", task.prompt if len(task.prompt) <= 160 else task.prompt[:157] + "…"),
            ("runs", task.schedule.describe()),
            ("folder", task.cwd),
            ("workspace", "isolated git copy per run" if task.workspace == "worktree"
             else "directly in the folder"),
            ("access", task.access),
            ("tools", ", ".join(group for group in task.tools if group != "mcp")),
            ("mcp", task.describe_mcp()),
            ("skills", task.describe_skills()),
            ("model", task.describe_model())]
    if show_signed_out:
        how = {"password": " (Windows password)", "s4u": " (no password)"}.get(
            task.signed_out_logon, "")
        rows.append(("signed out", f"keeps running{how}" if task.run_signed_out
                     else "skipped"))
    for label, value in rows:
        body.append(f"  {label:<11}", style="dim")
        body.append(f"{value}\n")
    if task.run_signed_out and task.signed_out_logon != "password" and keyring:
        body.append("  keys in Windows Credential Manager are unreadable while signed "
                    "out; use the file credential store\n", style="yellow")
    if task.access == "full-access":
        body.append("  full access runs unattended on your host without isolation\n",
                    style="bold red")
    if task.mcp_servers:
        body.append("  MCP tools from these servers run without asking\n", style="yellow")
    if task.workspace == "project" and {"edit", "commands"} & set(task.tools):
        body.append("  edits land directly in your working tree\n", style="yellow")
    return body


class _Steps:
    def __init__(self):
        self.count = 0

    def __call__(self, label: str) -> str:
        self.count += 1
        return f"step {self.count} · {label}"


def _clean_name(raw: str) -> str:
    if not any(char.isalnum() for char in raw):
        raise CommandError("that name has no letters or digits")
    swapped = "".join(char if char.isalnum() or char in "-_" else " " for char in raw)
    cleaned = "-".join(part.strip("-_") or "-" for part in swapped.split())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    if not cleaned:
        raise CommandError("that name has no usable characters")
    return cleaned[:48]
