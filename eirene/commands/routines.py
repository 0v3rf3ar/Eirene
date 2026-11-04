"""/routines: review scheduled routines, their runs, and what each run produced."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from rich.text import Text

from ..core.errors import CommandError, SchedulerError
from ..scheduling import backend
from ..scheduling.base import Task, load_tasks, save_tasks
from ..scheduling import worktree
from ..scheduling.history import finished_runs, last_start, load_output, remove_history
from ..ui import art
from ..ui.chat import Block
from . import register
from .routine_options import (Cancelled, choice, pick_mcp, pick_model, pick_skills, pick_tools,
                              text, with_mcp)


@register("routines", "review scheduled routines, runs and outputs")
async def run(app, args: str) -> None:
    tasks = load_tasks()
    if not tasks:
        app.say("no routines yet - make one with /schedule")
        return
    engine = backend()
    # Each status is a scheduler query (schtasks, systemctl, launchctl); off the UI loop.
    states = await asyncio.to_thread(_states, tasks, engine)
    await app.push(Block(_overview(tasks, engine, states)))

    options = [(task.id, task.name, _last_line(task)) for task in tasks]
    options.append(("", "done", ""))
    chosen = await app.ask_choice("open a routine", options)
    target = next((task for task in tasks if task.id == chosen), None)
    if target is not None:
        await _routine(app, engine, tasks, target)


def _states(tasks: list[Task], engine) -> dict[str, str]:
    states = {}
    for task in tasks:
        try:
            states[task.id] = engine.status(task) if engine.available else "unsupported"
        except SchedulerError as exc:
            states[task.id] = exc.user_message()
    return states


def _overview(tasks: list[Task], engine, states: dict[str, str] | None = None) -> Text:
    states = states if states is not None else _states(tasks, engine)
    body = Text()
    body.append(f"{art.icon('task')} {len(tasks)} routine{'s' if len(tasks) != 1 else ''}\n",
                style="bold")
    for task in tasks:
        state = states.get(task.id, "unknown")
        body.append(f"  {task.name}", style="bold")
        body.append(f"  {task.id}", style="dim")
        if not task.enabled:
            body.append("  disabled", style="yellow")
        body.append("\n")
        body.append(f"    {task.schedule.describe()} · {state}\n", style="dim")
        body.append(f"    {task.describe_access()}\n", style="dim")
        body.append(f"    {task.cwd}\n", style="dim")
        body.append(f"    {_clip(task.prompt, 100)}\n", style="dim")
        body.append(f"    last run: {_last_line(task)}\n",
                    style="dim" if _last_ok(task) is not False else "red")
        if not Path(task.cwd).is_dir():
            body.append("    ! its folder is gone; runs will fail until it is back\n",
                        style="red")
        copies = len(worktree.kept(task.id))
        if copies:
            body.append(f"    {copies} kept git cop{'y' if copies == 1 else 'ies'} with "
                        "changes to review or discard\n", style="yellow")
        problem = _missed(task, engine)
        if problem:
            body.append(f"    ! {problem}\n", style="red")
    return body


GRACE = 600  # seconds a scheduler may take to start a run before it counts as missed


def _missed(task: Task, engine, now: float | None = None) -> str:
    """Explain a signed-out run that should have started but left no trace."""
    if not (task.run_signed_out and task.enabled):
        return ""
    now = time.time() if now is None else now
    started = last_start(task.id) or 0.0
    due = task.schedule.last_due(now - GRACE, task.created)
    missed = due is not None and started < due - 60
    changed = None
    if task.signed_out_logon == "password":
        try:
            changed = engine.password_changed_at()
        except Exception:  # noqa: BLE001 - diagnostics must not break the listing
            changed = None
    stale = changed is not None and changed > task.created + 60 and started < changed
    if stale:
        lead = f"the run due {_when(due)} did not start; " if missed else ""
        return (f"{lead}your Windows password changed on {_when(changed)}, after this "
                "routine was created, and no run has started since; Windows cannot start "
                "it with an old password. Remove the routine and create it again")
    if missed:
        return (f"the run due {_when(due)} did not start (the PC may have been off or "
                "asleep; if your Windows password changed, remove and recreate the routine)")
    return ""


async def _routine(app, engine, tasks: list[Task], task: Task) -> None:
    runs = finished_runs(task.id)
    copies = worktree.kept(task.id)
    options = [
        ("latest", "latest output", _last_line(task)),
        ("history", "run history", f"{len(runs)} recorded"),
        ("details", "settings", task.describe_access()),
        ("edit", "edit", "prompt, model, access, tools, MCP servers, skills"),
        ("run", "run now", "started by the system scheduler" if task.enabled
         else "enable it first"),
        ("toggle", "disable" if task.enabled else "enable", task.schedule.describe()),
    ]
    if copies:
        options.append(("copies", "kept git copies",
                        f"{len(copies)} with changes; review or discard"))
    options += [("remove", "remove", "uninstall and forget its history and copies"),
                ("", "done", "")]
    action = await app.ask_choice(task.name, options)
    if action == "latest":
        await _show_run(app, task, runs[0] if runs else None)
    elif action == "history":
        await _history(app, task, runs)
    elif action == "details":
        await app.push(Block(_details(task)))
    elif action == "edit":
        await _edit(app, tasks, task)
    elif action == "run":
        await _run_now(app, engine, task)
    elif action == "toggle":
        await _toggle(app, engine, tasks, task)
    elif action == "copies":
        await _copies(app, task, copies)
    elif action == "remove":
        await _remove(app, engine, tasks, task)


async def _edit(app, tasks: list[Task], task: Task) -> None:
    """Change what a routine runs with; the next run reads the saved record."""
    while True:
        field = await app.ask_choice(f"edit {task.name}", [
            ("prompt", "what it does", _clip(task.prompt, 60)),
            ("model", "model", task.describe_model()),
            ("access", "access level", task.access),
            ("tools", "allowed tools", ", ".join(g for g in task.tools if g != "mcp")),
            ("mcp", "MCP servers", task.describe_mcp()),
            ("skills", "skills", task.describe_skills()),
            ("", "done", ""),
        ])
        if not field:
            return
        before = task.to_dict()
        try:
            changed = await _edit_field(app, task, field)
        except Cancelled:
            continue
        except CommandError as exc:
            app.say(exc.user_message(), "fail")
            continue
        if not changed:
            continue
        try:
            save_tasks(tasks)
        except SchedulerError as exc:
            _restore(task, before)
            app.say(exc.user_message(), "fail")
            return
        app.say(f"{art.icon('ok')} {task.name}: {_edited(task, field)}; applies from the next run")


async def _edit_field(app, task: Task, field: str) -> bool:
    if field == "prompt":
        value = await text(app, "what should the routine do?")
        if len(value) > 4000:
            raise CommandError("that prompt is too long for a scheduled task")
        task.prompt = value
    elif field == "model":
        picked = await pick_model(app, "which model should it use?", keep=task.describe_model())
        if picked is None:
            return False
        task.provider, task.model = picked
    elif field == "access":
        access = await choice(app, "access level", [
            ("sandboxed", "sandboxed (recommended)",
             "workspace only; commands have no network; nothing outside is reachable"),
            ("full-access", "full access", "host files, network and commands without isolation"),
        ])
        if access == "full-access" and task.access != "full-access":
            sure = await choice(app, "full access runs unattended on your host without isolation", [
                ("no", "keep it sandboxed", ""), ("full-access", "yes, full access", "")])
            if sure != "full-access":
                return False
        task.access = access
    elif field == "tools":
        task.tools = with_mcp(await pick_tools(app, "allowed tools"), task.mcp_servers)
    elif field == "mcp":
        servers = await pick_mcp(app, "MCP servers it may use", keep=task.describe_mcp())
        if servers is None:
            return False
        task.mcp_servers = servers
        task.tools = with_mcp(task.tools, servers)
    elif field == "skills":
        changed, skills = await pick_skills(app, "skills it may load", keep=task.describe_skills())
        if not changed:
            return False
        task.skills = skills
    return True


def _edited(task: Task, field: str) -> str:
    return {
        "prompt": "prompt updated",
        "model": f"model {task.describe_model()}",
        "access": f"access {task.access}",
        "tools": "tools " + ", ".join(g for g in task.tools if g != "mcp"),
        "mcp": f"MCP servers {task.describe_mcp()}",
        "skills": f"skills {task.describe_skills()}",
    }[field]


def _restore(task: Task, before: dict) -> None:
    saved = Task.from_dict(before)
    for name in ("prompt", "provider", "model", "access", "tools", "mcp_servers", "skills"):
        setattr(task, name, getattr(saved, name))


async def _run_now(app, engine, task: Task) -> None:
    if not task.enabled:
        app.say(f"{task.name} is disabled; enable it to run it", "warn")
        return
    # The scheduler starts it, so the run outlives this window and sees the same
    # environment as a scheduled run.
    try:
        note = await asyncio.to_thread(engine.run_now, task)
    except SchedulerError as exc:
        app.say(exc.user_message(), "fail")
        return
    app.say(f"{art.icon('ok')} {note}; its output appears here in /routines when done")


async def _toggle(app, engine, tasks: list[Task], task: Task) -> None:
    wanted = not task.enabled
    try:
        note = await asyncio.to_thread(engine.set_enabled, task, wanted)
    except SchedulerError as exc:
        app.say(exc.user_message(), "fail")
        return
    task.enabled = wanted
    try:
        save_tasks(tasks)
    except SchedulerError as exc:
        task.enabled = not wanted
        try:
            await asyncio.to_thread(engine.set_enabled, task, not wanted)
        except SchedulerError:
            pass
        app.say(exc.user_message(), "fail")
        return
    app.say(f"{art.icon('ok')} {task.name} {'enabled' if wanted else 'disabled'} ({note})")


async def _copies(app, task: Task, copies) -> None:
    total = await asyncio.to_thread(lambda: sum(worktree.size(path) for path in copies))
    body = Text()
    body.append(f"{art.icon('task')} {task.name} · {len(copies)} kept "
                f"cop{'y' if len(copies) == 1 else 'ies'} · {_bytes(total)}\n", style="bold")
    for path in copies:
        body.append(f"  {path}\n")
    body.append("\n  bring commits back with: git fetch PATH eirene/RUN_ID\n", style="dim")
    await app.push(Block(body))
    choice = await app.ask_choice(f"discard {len(copies)} kept "
                                  f"cop{'y' if len(copies) == 1 else 'ies'}?", [
        ("keep", "keep them", "review first"),
        ("discard", "discard all", "deletes the copies and any changes in them"),
    ])
    if choice != "discard":
        return
    try:
        gone = await asyncio.to_thread(worktree.remove_kept, task.id)
    except OSError as exc:
        app.say(f"could not delete every copy: {exc}", "fail")
        return
    app.say(f"{art.icon('ok')} discarded {gone} cop{'y' if gone == 1 else 'ies'}, "
            f"freed {_bytes(total)}")


def _bytes(count: int) -> str:
    size = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


async def _history(app, task: Task, runs: list[dict]) -> None:
    if not runs:
        app.say(f"{task.name} has not run yet")
        return
    options = [(str(index), _when(item.get("ts")), _run_line(item))
               for index, item in enumerate(runs)]
    options.append(("", "done", ""))
    chosen = await app.ask_choice(f"{task.name} · recent runs", options)
    if chosen:
        await _show_run(app, task, runs[int(chosen)])


async def _show_run(app, task: Task, item: dict | None) -> None:
    if item is None:
        app.say(f"{task.name} has not run yet")
        return
    saved = load_output(task.id, str(item.get("run") or "")) or {}
    body = Text()
    body.append(f"{art.icon('task')} {task.name} · {_when(item.get('ts'))}\n", style="bold")
    rows = [("result", _run_line(item))]
    if item.get("attempts"):
        rows.append(("attempts", str(item["attempts"])))
    tokens = (saved.get("input_tokens") or 0) + (saved.get("output_tokens") or 0)
    if tokens:
        rows.append(("tokens", f"{saved.get('input_tokens', 0)} in · "
                               f"{saved.get('output_tokens', 0)} out"))
    if saved.get("model"):
        rows.append(("model", f"{saved.get('provider') or ''} / {saved['model']}"))
    if item.get("session"):
        rows.append(("session", str(item["session"])))
    if item.get("worktree"):
        gone = "" if Path(item["worktree"]).exists() else " (discarded)"
        rows.append(("changes", f"kept in {item['worktree']}{gone}"))
    for label, value in rows:
        body.append(f"  {label:<11}", style="dim")
        body.append(f"{value}\n")
    for error in saved.get("errors") or item.get("errors") or []:
        body.append(f"  ! {error}\n", style="red")
    output = str(saved.get("output") or "").strip()
    if output:
        body.append("\n")
        body.append(output)
    elif item.get("event") == "finished" and not saved:
        body.append("\n  no saved output for this run\n", style="dim")
    await app.push(Block(body))


def _details(task: Task) -> Text:
    body = Text()
    body.append(f"{art.icon('task')} {task.name} settings\n", style="bold")
    rows = [("id", task.id), ("runs", task.schedule.describe()),
            ("folder", task.cwd),
            ("workspace", "isolated git copy per run" if task.workspace == "worktree"
             else "directly in the folder"),
            ("access", task.access),
            ("tools", ", ".join(group for group in task.tools if group != "mcp")),
            ("mcp", task.describe_mcp()), ("skills", task.describe_skills()),
            ("model", task.describe_model()),
            ("timeout", f"{task.timeout}s per attempt"),
            ("retries", f"{task.retries} (wait {task.retry_delay}s)"),
            ("overlap", "allowed" if task.allow_overlap else "skipped while running"),
            ("timezone", task.timezone)]
    if task.run_signed_out:
        how = {"password": " (Windows password)", "s4u": " (no password)"}.get(
            task.signed_out_logon, "")
        rows.append(("signed out", f"keeps running{how}"))
    for label, value in rows:
        body.append(f"  {label:<11}", style="dim")
        body.append(f"{value}\n")
    body.append("\n")
    body.append(task.prompt)
    return body


async def _remove(app, engine, tasks: list[Task], task: Task) -> None:
    # Forget the record first: undoing that only rewrites tasks.json, while undoing
    # an uninstall would need the routine's Windows password again.
    try:
        save_tasks([t for t in tasks if t.id != task.id])
    except SchedulerError as exc:
        app.say(exc.user_message(), "fail")
        return
    try:
        note = await asyncio.to_thread(engine.remove, task)
    except SchedulerError as exc:
        try:
            save_tasks(tasks)
        except SchedulerError:
            pass
        app.say(exc.user_message(), "fail")
        return
    await asyncio.to_thread(remove_history, task.id)
    app.say(f"{art.icon('ok')} {note}")


def _last(task: Task) -> dict | None:
    runs = finished_runs(task.id, 1)
    return runs[0] if runs else None


def _last_ok(task: Task) -> bool | None:
    item = _last(task)
    if item is None or item.get("event") == "skipped":
        return None
    return bool(item.get("ok"))


def _last_line(task: Task) -> str:
    item = _last(task)
    if item is None:
        return "never"
    return f"{_when(item.get('ts'))} · {_run_line(item)}"


def _run_line(item: dict) -> str:
    if item.get("event") == "skipped":
        return f"skipped ({item.get('reason', 'not run')})"
    status = "ok" if item.get("ok") else str(item.get("status") or f"exit {item.get('exit_code')}")
    if not item.get("ok") and item.get("exit_code") not in (None, 1):
        status += f" (exit {item.get('exit_code')})"
    line = f"{status} in {float(item.get('seconds') or 0):.0f}s"
    detail = item.get("summary") or next(iter(item.get("errors") or []), "")
    return f"{line} · {_clip(detail, 80)}" if detail else line


def _when(ts) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))
    except (TypeError, ValueError, OverflowError):
        return "unknown time"


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"
