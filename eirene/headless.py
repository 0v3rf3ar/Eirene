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
from .core.errors import ConfigError, EireneError, error_kind
from .core.modes import Mode
from .core.session import Session
from .scheduling.base import BUDGET_MARGIN, find_task
from .scheduling.history import lock_for, record
from .tools.sandbox import Sandbox

TASK_TIMEOUT = 3600
# Exit codes by failure class; anything else that failed exits 1.
EXIT_CODES = {"config": 3, "auth": 4, "network": 5, "incomplete": 6}
TOOL_CALL_LIMIT = 200
STREAM_RESULT_CHARS = 2000


class RunOutput:
    """Collect one final JSON result while keeping activity on stderr."""

    def __init__(self, text: str, json_output: bool, quiet: bool, stream: bool = False):
        self.stream = stream
        self.json_output = json_output or stream
        # A stream carries tool activity on stdout; stderr keeps only errors.
        self.quiet = quiet or stream
        self.result = dict(input=text, output="", provider=None, model=None, session=None,
                           input_tokens=0, output_tokens=0, cost_usd=None,
                           duration_seconds=0.0, status="completed", error_kind=None,
                           errors=[], tool_calls=[], files_edited=[], data=None)
        self.failed = False
        self._started = time.monotonic()
        self._last_notice = ""
        # Text after a tool call starts a new model message; keep it a new paragraph.
        self._after_tool = False

    def line(self, event_type: str, /, **fields) -> None:
        """One streamed JSON event; a no-op unless --stream-json."""
        if self.stream:
            sys.stdout.write(json.dumps({"type": event_type, **fields}, ensure_ascii=True) + "\n")
            sys.stdout.flush()

    def write(self, text: str) -> None:
        self.result["output"] += text
        if self.stream:
            self.line("text", text=text)
        elif not self.json_output:
            sys.stdout.write(safe_text(text))
            sys.stdout.flush()

    def error(self, text: str, kind: str = "failed") -> None:
        self.failed = True
        self.result["error_kind"] = self.result["error_kind"] or kind
        self.result["errors"].append(text)
        self.line("error", text=text, kind=kind)
        _err(text)

    def exit_code(self) -> int:
        return EXIT_CODES.get(self.result["error_kind"], 1) if self.failed else 0

    def event(self, event) -> None:
        if isinstance(event, agent_mod.Answer):
            if self._after_tool and self.result["output"].strip() and event.text.strip():
                self.write("\n" if self.result["output"].endswith("\n") else "\n\n")
            if event.text.strip():
                self._after_tool = False
            self.write(event.text)
        elif isinstance(event, agent_mod.ToolStarted):
            self._after_tool = True
            if event.name != "read_output":
                self.line("tool_start", id=event.id, name=event.name, label=event.label,
                          kind=event.kind)
            _emit(event, self.quiet)
        elif isinstance(event, agent_mod.ToolFinished):
            self._after_tool = True
            if event.name != "read_output":
                self._record_tool(event)
            _emit(event, self.quiet)
        elif isinstance(event, agent_mod.TurnDone):
            self.result["input_tokens"] += event.usage.input_tokens
            self.result["output_tokens"] += event.usage.output_tokens
            self.result["status"] = event.status
            self.line("turn_done", status=event.status, seconds=round(event.seconds, 3),
                      input_tokens=event.usage.input_tokens,
                      output_tokens=event.usage.output_tokens)
            if event.status != "completed" and not self.failed:
                kind = "incomplete" if event.status in ("incomplete", "blocked") else "failed"
                self.error(f"run {event.status}: {self._last_notice or 'stopped before finishing'}",
                           kind)
            if not self.json_output:
                self.write("\n")
        elif isinstance(event, agent_mod.Failed):
            self.error(event.text, event.kind or "failed")
        elif isinstance(event, agent_mod.Notice):
            if not event.transient:
                self._last_notice = event.text
                self.line("notice", text=event.text)
            _emit(event, self.quiet)
        elif isinstance(event, agent_mod.PlanChanged):
            self.line("plan", steps=event.steps, explanation=event.explanation)
        else:
            _emit(event, self.quiet)

    def _record_tool(self, event) -> None:
        calls = self.result["tool_calls"]
        if len(calls) < TOOL_CALL_LIMIT:
            calls.append(dict(name=event.name, label=event.label, is_error=event.is_error,
                              seconds=round(event.seconds, 3)))
        self.result["tool_call_count"] = self.result.get("tool_call_count", 0) + 1
        edited = self.result["files_edited"]
        if event.name in agent_mod.CHANGE_TOOLS and not event.is_error and event.label not in edited:
            edited.append(event.label)
        self.line("tool_end", id=event.id, name=event.name, label=event.label,
                  is_error=event.is_error, seconds=round(event.seconds, 3),
                  result=event.result[:STREAM_RESULT_CHARS])

    def finish(self, code: int, *, emit: bool = True) -> None:
        self.result["duration_seconds"] = round(time.monotonic() - self._started, 3)
        if code and self.result["status"] == "completed":
            self.result["status"] = {124: "timeout", 130: "interrupted"}.get(code, "failed")
        self.result["exit_code"] = code
        if not emit:
            return
        if self.stream:
            self.line("result", **self.result)
        elif self.json_output:
            sys.stdout.write(json.dumps(self.result, ensure_ascii=True) + "\n")
            sys.stdout.flush()


def run_prompt(text: str, cwd: Path, *, provider: str = "", model: str = "",
               mode: str = "auto", quiet: bool = False,
               task_timeout: int = TASK_TIMEOUT, json_output: bool = False,
               choices: list[str] | None = None,
               inputs: list[str] | None = None,
               permissions: str = "", tool_groups: list[str] | None = None,
               stream_json: bool = False, step_limit: int | None = None,
               token_limit: int | None = None, instructions: str = "",
               mcp_servers: list[str] | None = None, skills: list[str] | None = None,
               strict: bool = False, _result_sink: dict | None = None) -> int:
    """Run one prompt and print the answer."""
    output = RunOutput(text, json_output, quiet, stream_json)
    try:
        code = asyncio.run(_drive(text, cwd, provider, model, mode, quiet,
                                 task_timeout, output, choices, inputs,
                                 permissions=permissions, tool_groups=tool_groups,
                                 step_limit=step_limit, token_limit=token_limit,
                                 instructions=instructions, mcp_servers=mcp_servers,
                                 skills=skills, strict=strict))
    except KeyboardInterrupt:
        output.error("interrupted", "interrupted")
        code = 130
    except EireneError as exc:
        output.error(exc.user_message(), error_kind(exc))
        code = 1
    except Exception as exc:  # noqa: BLE001
        output.error(f"headless run failed: {exc}")
        code = 1
    if code == 1:
        code = output.exit_code() or 1
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
        record(task.id, "finished", exit_code=1, ok=False, seconds=0.0, attempts=0,
               status="failed", errors=[f"working directory is gone: {task.cwd}"])
        return stopped(f"task working directory is gone: {task.cwd}", 1)
    lock = lock_for(task.id)
    # The lock must outlive every attempt, or a slow retry looks abandoned.
    if not task.allow_overlap and not lock.acquire(task.budget + BUDGET_MARGIN):
        record(task.id, "skipped", reason="previous run still active")
        return stopped(f"task '{task.name}' skipped: previous run still active", 0)
    previous = {key: os.environ.get(key) for key in task.env}
    os.environ.update(task.env)
    started = time.time()
    run_id = time.strftime("%Y%m%d-%H%M%S", time.localtime(started)) + f"-{os.getpid()}"
    record(task.id, "started", run=run_id, name=task.name, cwd=task.cwd)
    code, attempt = 1, 0
    result: dict = {}
    tree = None
    kept = ""
    try:
        if task.workspace == "worktree":
            from .scheduling import worktree
            try:
                tree = worktree.create(task.id, run_id, cwd)
            except EireneError as exc:
                result = {"output": "", "errors": [exc.user_message()], "status": "failed"}
                _err(exc.user_message())
                raise _SetupFailed from exc
            cwd = tree.cwd
        text = f"{prompts.TASK_PROMPT}\n{_access_note(task)}\n{task.prompt}"
        for attempt in range(task.retries + 1):
            code = run_prompt(text, cwd, provider=task.provider, model=task.model,
                              mode="auto", quiet=True, task_timeout=task.timeout,
                              json_output=json_output, permissions=task.access,
                              tool_groups=list(task.tools), mcp_servers=task.mcp_servers,
                              skills=task.skills, _result_sink=result)
            if code == 0:
                break
            if attempt < task.retries:
                record(task.id, "retry", run=run_id, attempt=attempt + 1, exit_code=code)
                time.sleep(task.retry_delay)
    except _SetupFailed:
        code = 1
    finally:
        if tree is not None:
            try:
                if tree.changed():
                    kept = str(tree.path)
                else:
                    tree.remove()
            except EireneError:
                kept = str(tree.path)
        try:
            _finish_task(task, run_id, code, attempt, started, result, kept)
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            lock.release()
    if json_output:
        result.update(input=task.prompt, task_id=task_id, attempts=attempt + 1)
        sys.stdout.write(json.dumps(result, ensure_ascii=True) + "\n")
        sys.stdout.flush()
    return code


class _SetupFailed(Exception):
    pass


def _access_note(task) -> str:
    return access_note(task.access, task.tools, task.workspace, task.mcp_servers)


def access_note(access: str, tool_groups, workspace: str = "project",
                mcp_servers: list[str] | None = None) -> str:
    """Tell the model what this unattended run may touch."""
    from .scheduling.base import TOOL_GROUP_HELP, describe_names
    groups = [group for group in tool_groups if group != "mcp" or mcp_servers]
    allowed = "; ".join(f"{group} ({TOOL_GROUP_HELP[group]})" for group in groups)
    place = ("a private git clone of the project (git works; commit there if useful); edits stay there for review"
             if workspace == "worktree" else "the project directory itself")
    servers = (f" MCP servers: {describe_names(mcp_servers, every='every enabled server')}."
               if mcp_servers else "")
    return (f"Access for this run: {access}. Allowed tools: {allowed}.{servers} "
            f"Workspace: {place}. Other tools are unavailable; do not try to work around them.")


def granted_servers(names: list[str] | None, config: Config, strict: bool = False) -> frozenset[str]:
    """MCP servers an unattended run may call; none unless named."""
    from .core.plugins import available_mcp_servers, merged_mcp_servers
    names = list(names or [])
    if not names:
        return frozenset()
    enabled = merged_mcp_servers(config)
    if names == ["*"]:
        return frozenset(enabled)
    if strict:
        known = available_mcp_servers(config)
        for name in names:
            if name not in known:
                raise ConfigError(f"unknown MCP server '{name}'; see /mcp")
            if name not in enabled:
                raise ConfigError(f"MCP server '{name}' is not enabled; turn it on in /mcp")
    return frozenset(names)


def chosen_skills(names: list[str] | None, strict: bool = False) -> frozenset[str] | None:
    """Skills an unattended run may load; None keeps the saved settings."""
    if names is None:
        return None
    from .core import skills as skills_mod
    installed = {skill.name for skill in skills_mod.discover()}
    if names == ["*"]:
        return frozenset(installed)
    missing = [name for name in names if name not in installed]
    if missing:
        message = "unknown skill" + ("s" if len(missing) > 1 else "") + ": " + ", ".join(missing)
        if strict:
            raise ConfigError(message + "; see /skills")
        _err(message)
    return frozenset(name for name in names if name in installed)


def _finish_task(task, run_id: str, code: int, attempt: int, started: float,
                 result: dict, kept: str) -> None:
    from .scheduling.history import save_output
    summary = " ".join(str(result.get("output") or "").split())[:240]
    errors = [str(item) for item in result.get("errors") or []][:5]
    record(task.id, "finished", run=run_id, exit_code=code, ok=code == 0,
           seconds=time.time() - started, attempts=attempt + 1,
           status=result.get("status") or ("completed" if code == 0 else "failed"),
           summary=summary, errors=errors, session=result.get("session", ""),
           worktree=kept)
    try:
        save_output(task.id, run_id, {**result, "run": run_id, "task_id": task.id,
                                      "exit_code": code, "worktree": kept,
                                      "started": started, "seconds": time.time() - started})
    except EireneError as exc:
        _err(exc.user_message())
    if code != 0:
        config = Config.load()
        if config.get("notifications", False):
            from .core import notify
            notify.send(f"Eirene task failed: {task.name}",
                        f"exit {code} after {attempt + 1} attempt(s)")


async def _drive(text: str, cwd: Path, provider_key: str, model: str,
                 mode: str, quiet: bool, task_timeout: int = TASK_TIMEOUT,
                 output: RunOutput | None = None, choices: list[str] | None = None,
                 inputs: list[str] | None = None, *, permissions: str = "",
                 tool_groups: list[str] | None = None, step_limit: int | None = None,
                 token_limit: int | None = None, instructions: str = "",
                 mcp_servers: list[str] | None = None, skills: list[str] | None = None,
                 strict: bool = False) -> int:
    paths.ensure_tree()
    from .core.skills import remove_seeded_examples
    from .core.plugin_install import export_installed_skills
    remove_seeded_examples()
    export_installed_skills()
    config = Config.load()
    runtime_logging.configure(config)
    if permissions in ("sandboxed", "full-access"):
        # Process-local, like /permissions; Config.save never persists full access.
        config.set("permissions", permissions)
    box = Sandbox(cwd)
    session = Session.create(box.root)
    paths.use_session_temp(box.root, session.id)
    runner = agent_mod.Agent(session, config, box)
    runner.mode = Mode(mode) if mode in Mode._value2member_map_ else Mode.AUTO
    runner.mcp_servers = granted_servers(mcp_servers, config, strict)
    runner.skill_names = chosen_skills(skills, strict)
    if tool_groups is not None:
        # Naming a server is the grant; the tool group follows it.
        runner.tool_groups = frozenset(tool_groups) | ({"mcp"} if runner.mcp_servers else set())
    runner.step_limit, runner.token_limit = step_limit, token_limit
    output = output or RunOutput(text, False, quiet)
    output.result["session"] = session.id
    runner.reload_skills()
    from .headless_commands import HeadlessApp
    try:
        app = HeadlessApp(runner, output, provider_key, model, choices, inputs)
        output.line("start", session=session.id, cwd=str(box.root),
                    provider=output.result["provider"], model=output.result["model"],
                    mode=runner.mode.value,
                    tools=sorted(runner.tool_groups) if runner.tool_groups is not None else "all",
                    mcp=sorted(runner.mcp_servers),
                    skills=None if runner.skill_names is None else sorted(runner.skill_names))
        async with asyncio.timeout(task_timeout):
            if text.startswith("/"):
                await app.dispatch(text)
            elif instructions:
                await app._run_turn(f"{instructions}\n{text}", record_text=text)
            else:
                await app._run_turn(text)
    except TimeoutError:
        output.error(f"run exceeded {task_timeout}s and was stopped", "timeout")
        return 124
    finally:
        from .tools import processes
        await processes.stop_all()
        await runner.close()
        session.close()
        if runner.usage.turns:
            cost = runner.usage.estimated_cost(config.get("model_costs", {}))
            output.result["cost_usd"] = None if cost is None else round(cost, 6)
    return 1 if output.failed else 0


def _emit(event, quiet: bool) -> bool:
    """Print an event; True when it is a failure."""
    if isinstance(event, (agent_mod.ToolStarted, agent_mod.ToolFinished)) and event.name == "read_output":
        return False
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
