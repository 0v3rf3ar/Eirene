"""Bounded provider-neutral specialist execution using the normal agent policy."""
from __future__ import annotations

import asyncio
import copy
import json

from .config import Config
from .errors import ToolError
from .modes import Mode
from .plugin_resources import agent_definitions
from .session import Session
from ..tools.sandbox import Sandbox


def validate_tasks(raw, config):
    if not isinstance(raw, list) or not 1 <= len(raw) <= 8:
        raise ToolError("delegate_tasks needs 1 to 8 tasks")
    profiles = agent_definitions(config)
    tasks = []
    for task in raw:
        if not isinstance(task, dict) or not isinstance(task.get("prompt"), str) or not task["prompt"].strip():
            raise ToolError("each delegated task needs a nonempty prompt")
        if len(task["prompt"]) > 60000:
            raise ToolError("delegated task prompt exceeds 60000 characters")
        name = task.get("agent", "")
        if not isinstance(name, str) or name and name not in profiles:
            raise ToolError(f"plugin agent '{name}' is disabled or unavailable; use its namespaced name")
        read_only = task.get("read_only", True)
        if not isinstance(read_only, bool):
            raise ToolError("task read_only must be a boolean")
        tasks.append({"prompt": task["prompt"], "agent": name, "read_only": read_only})
    return tasks, profiles


async def run_tasks(parent, raw, on_output=None):
    from .agent import Agent, Answer, Failed, ToolStarted, TurnDone
    from ..providers.registry import build
    from ..tools import processes

    if parent._delegation_depth:
        raise ToolError("delegated agents cannot start more agents")
    if parent.mode is Mode.PLAN:
        raise ToolError("agent execution is disabled in plan mode")
    tasks, profiles = validate_tasks(raw, parent.config)
    # Never race implementations in a shared workspace. Approval dialogs also
    # need serialization, even for independent reviewers.
    semaphore = asyncio.Semaphore(4 if all(t["read_only"] for t in tasks) else 1)
    dialog = asyncio.Lock()

    async def approve(*args):
        async with dialog:
            return await parent.approve(*args)

    async def choose(*args):
        async with dialog:
            return await parent.choose(*args)

    async def worker(index, task):
        async with semaphore:
            label = task["agent"] or f"task-{index + 1}"
            config = Config(copy.deepcopy(parent.config.data), parent.config.path)
            config.set("mode", Mode.PLAN.value if task["read_only"] else parent.mode.value)
            config.set("max_iterations", min(parent.iteration_limit or 40, 40))
            session = Session.create(parent.sandbox.root)
            child = Agent(session, config, Sandbox(parent.sandbox.root))
            child._delegation_depth = parent._delegation_depth + 1
            child.approve = approve if parent.approve else None
            child.choose = choose if parent.choose else None
            child.reload_skills()
            child.plugin_runtime.context = dict(parent.plugin_runtime.context)
            child.plugin_runtime.started = set(parent.plugin_runtime.started)
            child.plugin_runtime.ponytail_mode = parent.plugin_runtime.ponytail_mode
            text = task["prompt"]
            if task["agent"]:
                plugin, path, _, body = profiles[task["agent"]]
                from .plugins import expand_definition
                body = expand_definition(body, plugin.path)
                text = (f"Specialist profile: {label}\nPlugin directory: {plugin.path}\n"
                        f"Profile directory: {path.parent}\n{body}\n\nTask:\n{text}")
            text += ("\n\nReturn your completed findings with file references, verification evidence, "
                     "and any blockers. Follow the parent task's scope and host permissions.")
            replies, failures, status = [], [], "failed"
            try:
                child.use(build(parent.provider_key, config), parent.provider_key, parent.model)
                if on_output:
                    on_output(f"[{label}] started ({'read-only' if task['read_only'] else 'implementation'})\n")
                async with asyncio.timeout(600):
                    async for event in child.run(text):
                        if isinstance(event, Answer):
                            replies.append(event.text)
                        elif isinstance(event, Failed):
                            failures.append(event.text)
                        elif isinstance(event, ToolStarted) and on_output:
                            on_output(f"[{label}] {event.name}: {event.label}\n")
                        elif isinstance(event, TurnDone):
                            status = event.status
                            parent._delegated_usage.input_tokens += event.usage.input_tokens
                            parent._delegated_usage.output_tokens += event.usage.output_tokens
            except TimeoutError:
                failures.append("task timed out after 600 seconds; inspect any partial work before retrying")
            except Exception as exc:
                failures.append(str(exc))
            finally:
                try:
                    await child.close()
                finally:
                    await processes.stop_owned(session.id, since=0)
                    session.close()
            if failures:
                status = "failed"
            if on_output:
                on_output(f"[{label}] {status}\n")
            return {"agent": label, "status": status, "report": "\n".join(replies),
                    "errors": failures, "session_id": session.id}

    pending = [asyncio.create_task(worker(index, task)) for index, task in enumerate(tasks)]
    try:
        return json.dumps(await asyncio.gather(*pending), ensure_ascii=False)
    finally:
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
