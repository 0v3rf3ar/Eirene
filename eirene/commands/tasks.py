"""/tasks"""

from __future__ import annotations

import shlex

from rich.text import Text

from ..core.errors import SchedulerError
from ..scheduling import backend
from ..scheduling.base import load_tasks, save_tasks
from ..scheduling.history import last_result, runs
from ..ui import art
from ..ui.chat import Block
from ..tools import processes
from . import register


@register("tasks", "list the scheduled tasks")
async def run(app, args: str) -> None:
    tasks = load_tasks()
    if not tasks:
        app.say("no scheduled tasks - make one with /schedule")
        return

    engine = backend()
    body = Text()
    body.append(f"{art.icon('task')} {len(tasks)} scheduled\n", style="bold")
    for task in tasks:
        try:
            state = engine.status(task) if engine.available else "unsupported"
        except SchedulerError as exc:
            state = exc.user_message()
        body.append(f"  {task.name}", style="bold")
        body.append(f"  {task.id}\n", style="dim")
        body.append(f"    {task.schedule.describe()} · {state}\n", style="dim")
        body.append(f"    {'enabled' if task.enabled else 'disabled'} · retries "
                    f"{task.retries} · timeout {task.timeout}s · timezone {task.timezone}\n",
                    style="dim")
        body.append(f"    {task.cwd}\n", style="dim")
        body.append(f"    {task.prompt[:100]}\n", style="dim")
        last = last_result(task.id)
        if last:
            outcome = "ok" if last.get("ok") else f"exit {last.get('exit_code')}"
            body.append(f"    last run: {outcome} in {last.get('seconds', 0):.1f}s\n",
                        style="dim")
    await app.push(Block(body))

    options = []
    for task in tasks:
        options.extend([
            (f"run:{task.id}", f"run {task.name} now", "managed background run"),
            (f"toggle:{task.id}", f"{'disable' if task.enabled else 'enable'} {task.name}",
             task.schedule.describe()),
            (f"history:{task.id}", f"history for {task.name}", "recent runs"),
            (f"remove:{task.id}", f"remove {task.name}", task.schedule.describe()),
        ])
    options.append(("", "done", ""))
    chosen = await app.ask_choice("remove a task?", options)
    if not chosen:
        return

    action, _, task_id = chosen.partition(":")
    target = next((t for t in tasks if t.id == task_id), None)
    if target is None:
        return
    if action == "history":
        history = runs(target.id)
        detail = "\n".join(
            f"  {item.get('event')}" +
            (f" · exit {item.get('exit_code')}" if 'exit_code' in item else "")
            for item in history) or "  no runs yet"
        await app.push(Block(Text(f"{target.name} history\n{detail}")))
        return
    if action == "run":
        from ..app import invocation
        command = " ".join(shlex.quote(part) for part in shlex.split(invocation()))
        note = await processes.start(f"{command} --task {shlex.quote(target.id)}",
                                     app.sandbox.root)
        app.say(f"{art.icon('ok')} {note}; use the process tools to inspect it")
        return
    if action == "toggle":
        target.enabled = not target.enabled
        save_tasks(tasks)
        app.say(f"{art.icon('ok')} {target.name} "
                f"{'enabled' if target.enabled else 'disabled'}")
        return
    try:
        note = engine.remove(target)
        try:
            save_tasks([t for t in tasks if t.id != task_id])
        except SchedulerError:
            engine.install(target)
            raise
    except SchedulerError as exc:
        app.say(exc.user_message(), "fail")
        return
    app.say(f"{art.icon('ok')} {note}")
