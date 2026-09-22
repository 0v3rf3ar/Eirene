"""Non-interactive runs for scheduled tasks and -p."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

from .core import agent as agent_mod
from .core import paths, prompt as prompts
from .core.config import Config
from .core import logging as runtime_logging
from .core.errors import EireneError
from .core.modes import Mode
from .core.session import Session
from .providers import registry as providers
from .scheduling.base import find_task
from .scheduling.history import lock_for, record
from .tools.sandbox import Sandbox

TASK_TIMEOUT = 3600


def run_prompt(text: str, cwd: Path, *, provider: str = "", model: str = "",
               mode: str = "auto", quiet: bool = False,
               task_timeout: int = TASK_TIMEOUT) -> int:
    """Run one prompt and print the answer."""
    try:
        return asyncio.run(_drive(text, cwd, provider, model, mode, quiet,
                                  task_timeout))
    except KeyboardInterrupt:
        _err("interrupted")
        return 130
    except EireneError as exc:
        _err(exc.user_message())
        return 1


def run_task(task_id: str) -> int:
    """Run a scheduled task by id."""
    task = find_task(task_id)
    if not task:
        _err(f"no task '{task_id}'")
        return 1
    if not task.enabled:
        _err(f"task '{task.name}' is disabled")
        return 0
    cwd = Path(task.cwd)
    if not cwd.is_dir():
        _err(f"task working directory is gone: {task.cwd}")
        return 1
    text = f"{prompts.TASK_PROMPT}\n{task.prompt}"
    lock = lock_for(task.id)
    if not task.allow_overlap and not lock.acquire(task.timeout + 300):
        record(task.id, "skipped", reason="previous run still active")
        _err(f"task '{task.name}' skipped: previous run still active")
        return 0
    previous = {key: os.environ.get(key) for key in task.env}
    os.environ.update(task.env)
    started = time.time()
    record(task.id, "started", name=task.name, cwd=task.cwd)
    code, attempt = 1, 0
    try:
        for attempt in range(task.retries + 1):
            code = run_prompt(text, cwd, provider=task.provider, model=task.model,
                              mode="auto", quiet=True, task_timeout=task.timeout)
            if code == 0:
                break
            if attempt < task.retries:
                record(task.id, "retry", attempt=attempt + 1, exit_code=code)
                time.sleep(task.retry_delay)
        record(task.id, "finished", exit_code=code, ok=code == 0,
               seconds=time.time() - started, attempts=attempt + 1)
        if code != 0:
            config = Config.load()
            if config.get("notifications", False):
                from .core import notify
                notify.send(f"Eirene task failed: {task.name}",
                            f"exit {code} after {attempt + 1} attempt(s)")
        return code
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        lock.release()


async def _drive(text: str, cwd: Path, provider_key: str, model: str,
                 mode: str, quiet: bool, task_timeout: int = TASK_TIMEOUT) -> int:
    paths.ensure_tree()
    config = Config.load()
    runtime_logging.configure(config)
    key = provider_key or config.provider or ""
    if not key:
        raise EireneError("no provider configured; run eirene and use /connect")
    key = providers.resolve_alias(key)
    chosen = model or config.provider_config(key).get("model") or config.model \
        or providers.default_model(key)
    if not chosen:
        raise EireneError(f"no model set for {key}")

    box = Sandbox(cwd)
    session = Session.create(box.root)
    session.add_note("headless", prompt=text[:400], provider=key, model=chosen)
    runner = agent_mod.Agent(session, config, box)
    runner.mode = Mode(mode) if mode in Mode._value2member_map_ else Mode.AUTO
    runner.reload_skills()
    runner.use(providers.build(key, config), key, chosen)

    failed = False
    try:
        async with asyncio.timeout(task_timeout):
            async for event in runner.run(text):
                failed = _emit(event, quiet) or failed
    except TimeoutError:
        _err(f"task exceeded {task_timeout}s and was stopped")
        return 124
    finally:
        await runner.close()
        session.close()
    return 1 if failed else 0


def _emit(event, quiet: bool) -> bool:
    """Print an event; True when it is a failure."""
    if isinstance(event, agent_mod.Answer):
        sys.stdout.write(event.text)
        sys.stdout.flush()
    elif isinstance(event, agent_mod.ToolStarted) and not quiet:
        _err(f"· {event.name} {event.label}")
    elif isinstance(event, agent_mod.ToolFinished) and event.is_error:
        _err(f"! {event.name}: {event.result[:200]}")
    elif isinstance(event, agent_mod.Notice) and not quiet:
        _err(f"· {event.text}")
    elif isinstance(event, agent_mod.Failed):
        _err(f"error: {event.text}")
        return True
    elif isinstance(event, agent_mod.TurnDone):
        sys.stdout.write("\n")
        sys.stdout.flush()
        return event.status != "completed"
    return False


def _err(text: str) -> None:
    sys.stderr.write(text + "\n")
    sys.stderr.flush()
