"""Non-interactive runs for scheduled tasks and -p."""

from __future__ import annotations

from .core.text import safe_text

import asyncio
import json
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
from .scheduling.base import find_task
from .scheduling.history import lock_for, record
from .tools.sandbox import Sandbox

TASK_TIMEOUT = 3600


class RunOutput:
    """Collect one final JSON result while keeping activity on stderr."""

    def __init__(self, text: str, json_output: bool, quiet: bool):
        self.json_output, self.quiet = json_output, quiet
        self.result = dict(input=text, output="", provider=None, model=None,
                           input_tokens=0, output_tokens=0, status="completed",
                           errors=[], data=None)
        self.failed = False

    def write(self, text: str) -> None:
        self.result["output"] += text
        if not self.json_output:
            sys.stdout.write(safe_text(text))
            sys.stdout.flush()

    def error(self, text: str) -> None:
        self.failed = True
        self.result["errors"].append(text)
        _err(text)

    def event(self, event) -> None:
        if isinstance(event, agent_mod.Answer):
            self.write(event.text)
        elif isinstance(event, agent_mod.TurnDone):
            self.result["input_tokens"] += event.usage.input_tokens
            self.result["output_tokens"] += event.usage.output_tokens
            self.result["status"] = event.status
            self.failed = event.status != "completed" or self.failed
            if not self.json_output:
                self.write("\n")
        elif isinstance(event, agent_mod.Failed):
            self.error(event.text)
        else:
            _emit(event, self.quiet)

    def finish(self, code: int, *, emit: bool = True) -> None:
        if code and self.result["status"] == "completed":
            self.result["status"] = {124: "timeout", 130: "interrupted"}.get(code, "failed")
        self.result["exit_code"] = code
        if self.json_output and emit:
            sys.stdout.write(json.dumps(self.result, ensure_ascii=True) + "\n")
            sys.stdout.flush()


def run_prompt(text: str, cwd: Path, *, provider: str = "", model: str = "",
               mode: str = "auto", quiet: bool = False,
               task_timeout: int = TASK_TIMEOUT, json_output: bool = False,
               choices: list[str] | None = None,
               inputs: list[str] | None = None,
               _result_sink: dict | None = None) -> int:
    """Run one prompt and print the answer."""
    output = RunOutput(text, json_output, quiet)
    try:
        code = asyncio.run(_drive(text, cwd, provider, model, mode, quiet,
                                 task_timeout, output, choices, inputs))
    except KeyboardInterrupt:
        output.error("interrupted")
        code = 130
    except EireneError as exc:
        output.error(exc.user_message())
        code = 1
    except Exception as exc:  # noqa: BLE001
        output.error(f"headless run failed: {exc}")
        code = 1
    output.finish(code, emit=_result_sink is None)
    if _result_sink is not None:
        _result_sink.update(output.result)
    return code


def run_task(task_id: str, *, json_output: bool = False) -> int:
    """Run a scheduled task by id."""
    task = find_task(task_id)

    def stopped(message: str, code: int) -> int:
        output = RunOutput(task.prompt if task else "", json_output, True)
        output.result["task_id"] = task_id
        if code:
            output.error(message)
        else:
            _err(message)
            output.result["status"] = "skipped"
        output.finish(code)
        return code

    if not task:
        return stopped(f"no task '{task_id}'", 1)
    if not task.enabled:
        return stopped(f"task '{task.name}' is disabled", 0)
    cwd = Path(task.cwd)
    if not cwd.is_dir():
        return stopped(f"task working directory is gone: {task.cwd}", 1)
    text = f"{prompts.TASK_PROMPT}\n{task.prompt}"
    lock = lock_for(task.id)
    if not task.allow_overlap and not lock.acquire(task.timeout + 300):
        record(task.id, "skipped", reason="previous run still active")
        return stopped(f"task '{task.name}' skipped: previous run still active", 0)
    previous = {key: os.environ.get(key) for key in task.env}
    os.environ.update(task.env)
    started = time.time()
    record(task.id, "started", name=task.name, cwd=task.cwd)
    code, attempt = 1, 0
    result = {} if json_output else None
    try:
        for attempt in range(task.retries + 1):
            code = run_prompt(text, cwd, provider=task.provider, model=task.model,
                              mode="auto", quiet=True, task_timeout=task.timeout,
                              json_output=json_output, _result_sink=result)
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
        if result is not None:
            result.update(input=task.prompt, task_id=task_id, attempts=attempt + 1)
            sys.stdout.write(json.dumps(result, ensure_ascii=True) + "\n")
            sys.stdout.flush()
        return code
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        lock.release()


async def _drive(text: str, cwd: Path, provider_key: str, model: str,
                 mode: str, quiet: bool, task_timeout: int = TASK_TIMEOUT,
                 output: RunOutput | None = None, choices: list[str] | None = None,
                 inputs: list[str] | None = None) -> int:
    paths.ensure_tree()
    from .core.skills import remove_seeded_examples
    remove_seeded_examples()
    config = Config.load()
    runtime_logging.configure(config)
    box = Sandbox(cwd)
    session = Session.create(box.root)
    runner = agent_mod.Agent(session, config, box)
    runner.mode = Mode(mode) if mode in Mode._value2member_map_ else Mode.AUTO
    runner.reload_skills()
    output = output or RunOutput(text, False, quiet)
    from .headless_commands import HeadlessApp
    try:
        app = HeadlessApp(runner, output, provider_key, model, choices, inputs)
        async with asyncio.timeout(task_timeout):
            if text.startswith("/"):
                await app.dispatch(text)
            else:
                await app._run_turn(text)
    except TimeoutError:
        output.error(f"task exceeded {task_timeout}s and was stopped")
        return 124
    finally:
        from .tools import processes
        await processes.stop_all()
        await runner.close()
        session.close()
    return 1 if output.failed else 0


def _emit(event, quiet: bool) -> bool:
    """Print an event; True when it is a failure."""
    if isinstance(event, agent_mod.Answer):
        sys.stdout.write(safe_text(event.text))
        sys.stdout.flush()
    elif isinstance(event, agent_mod.ToolStarted) and not quiet:
        _err(f"· {event.name} {event.label}")
    elif isinstance(event, agent_mod.ToolFinished) and event.is_error and not event.reused:
        _err(f"! {event.name}: {event.result[:200]}")
    elif isinstance(event, agent_mod.Notice) and not event.transient and not quiet:
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
    sys.stderr.write(safe_text(text) + "\n")
    sys.stderr.flush()
