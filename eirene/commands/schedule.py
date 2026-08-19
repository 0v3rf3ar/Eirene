"""/schedule"""

from __future__ import annotations

import re

from ..core.errors import CommandError, SchedulerError
from ..scheduling import backend
from ..scheduling.base import Task, load_tasks, new_id, parse_schedule, save_tasks
from ..ui import art
from . import register

EXAMPLES = [("every 30m", "every 30m", "twice an hour"),
            ("hourly", "hourly", "on the hour"),
            ("daily at 09:00", "daily at 09:00", "every morning"),
            ("mon at 18:30", "mon at 18:30", "once a week"),
            ("at startup", "at startup", "when you log in")]


@register("schedule", "schedule a task with the system scheduler",
          "/schedule [prompt]")
async def run(app, args: str) -> None:
    engine = backend()
    if not engine.available:
        raise CommandError("this platform has no scheduler backend")

    prompt = args.strip()
    if not prompt:
        prompt = (await app.ask_text("what should the task do?") or "").strip()
    if not prompt:
        app.say("cancelled")
        return
    if len(prompt) > 4000:
        raise CommandError("that prompt is too long for a scheduled task")

    name = (await app.ask_text("short name for the task") or "").strip()
    if not name:
        app.say("cancelled")
        return
    name = _clean_name(name)

    picked = await app.ask_choice("how often?", EXAMPLES + [("custom", "custom…", "")])
    if not picked:
        app.say("cancelled")
        return
    if picked == "custom":
        picked = (await app.ask_text("schedule, e.g. 'every 45m' or 'daily at 07:15'")
                  or "").strip()
        if not picked:
            app.say("cancelled")
            return
    schedule = parse_schedule(picked)

    task = Task(id=new_id(), name=name, prompt=prompt, cwd=str(app.sandbox.root),
                schedule=schedule, provider=app.agent.provider_key or "",
                model=app.agent.model or "")

    confirm = await app.ask_choice(
        f"create '{name}' {schedule.describe()} in {app.sandbox.root}?",
        [("yes", "yes, install it", engine.name), ("no", "no", "")])
    if confirm != "yes":
        app.say("cancelled")
        return

    installed = False
    try:
        note = engine.install(task)
        installed = True
        tasks = load_tasks()
        tasks.append(task)
        save_tasks(tasks)
    except SchedulerError as exc:
        if installed:
            try:
                engine.remove(task)
            except SchedulerError:
                pass
        raise CommandError(exc.user_message()) from exc
    app.say(f"{art.icon('ok')} {note} - runs {schedule.describe()}")
    for warning in engine.warnings():
        app.say(warning, "warn")


def _clean_name(raw: str) -> str:
    if not any(char.isalnum() for char in raw):
        raise CommandError("that name has no letters or digits")
    swapped = "".join(char if char.isalnum() or char in "-_" else " " for char in raw)
    cleaned = "-".join(part.strip("-_") or "-" for part in swapped.split())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    if not cleaned:
        raise CommandError("that name has no usable characters")
    return cleaned[:48]
