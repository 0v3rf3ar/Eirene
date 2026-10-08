"""The model-and-tools loop."""

from __future__ import annotations

import asyncio
import json
import platform
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, AsyncIterator, Awaitable, Callable

from ..providers import base as pbase
from ..providers.base import Done, TextDelta, ThinkingDelta, ToolCall
from ..tools import registry as tools
from ..tools.sandbox import Sandbox
from . import prompt as prompts
from . import questions
from . import skills as skills_mod
from .errors import Cancelled, EireneError, ProviderError, SandboxError, ToolError
from .modes import ALLOW, ASK, BLOCK, Mode, decide
from .session import Message, Session
from .usage import Usage, estimate_messages
from . import project as project_mod
from . import hooks as hook_mod
from .mcp import MCPManager
from .plugins import merged_hooks, merged_mcp_servers
from . import plans as plan_mod
from . import artifacts
from .tool_memory import compact_output, fingerprint
from .logging import get as get_logger

CHANGE_TOOLS = ("write_file", "edit_file", "apply_patch")
CONTEXT_WARNING = 60_000
ASIDE_HISTORY = 40
# Reasoning models spend tokens thinking before they answer.
TITLE_TOKENS = 1024
TRUNCATED = ("length", "max_tokens", "max_output_tokens")
DEFAULT_MAX_TOKENS = 16384
RETRY_ATTEMPTS = 12
RETRY_DELAY = 1.0
RETRY_MAX_DELAY = 60.0
CONNECTION_STATUS_AFTER = 15.0
# 0 means the agent keeps going until the work is done.
DEFAULT_ITERATIONS = 0

THINKING = "thinking"
WRITING = "writing"
RUNNING = "running"
ANSWERING = "answering"
WAITING = "waiting for confirmation"

YES, NO, ALWAYS = "yes", "no", "always"


@dataclass
class Phase:
    name: str


@dataclass
class Thought:
    text: str


@dataclass
class Answer:
    text: str


@dataclass
class ToolPreview:
    id: str
    name: str
    label: str
    diff: str


@dataclass
class ToolStarted:
    id: str
    name: str
    label: str
    kind: str


@dataclass
class ToolOutput:
    id: str
    chunk: str
    artifact_id: str = ""


@dataclass
class ToolFinished:
    id: str
    name: str
    label: str
    result: str
    is_error: bool
    seconds: float
    artifact_id: str = ""
    reused: bool = False


@dataclass
class Tokens:
    input_tokens: int
    output_tokens: int


@dataclass
class PlanChanged:
    steps: list[dict[str, str]]
    explanation: str = ""


@dataclass
class Notice:
    text: str
    transient: bool = False
    phase: str = "working"


@dataclass
class Failed:
    text: str


@dataclass
class TurnDone:
    seconds: float
    thinking_seconds: float
    usage: Usage = field(default_factory=Usage)
    status: str = "completed"


AgentEvent = (Phase | Thought | Answer | ToolPreview | ToolStarted | ToolOutput
              | ToolFinished | Tokens | PlanChanged | Notice | Failed | TurnDone)

ApprovalFn = Callable[[str, str, str, str], Awaitable[str]]
ChoiceFn = Callable[[str, list], Awaitable[str | None]]


class Agent:
    """Drives one session against one provider."""

    def __init__(self, session: Session, config, sandbox: Sandbox):
        self.session = session
        self.config = config
        self.sandbox = sandbox
        from ..tools.search import SearchService
        self.search_service = SearchService(config)
        from .platforms import Host
        self.host = Host.detect()
        self.mode = Mode(config.mode) if config.mode in Mode._value2member_map_ else Mode.MANUAL
        self.provider = None
        self.provider_key = ""
        self.model = ""
        self.usage = Usage()
        self.skills: list[skills_mod.Skill] = []
        self.approve: ApprovalFn | None = None
        self.choose: ChoiceFn | None = None
        self.always: set[str] = set()
        self.project = project_mod.discover(self.sandbox.root)
        definitions = {name: {**definition, "_isolation": config.get("execution_isolation", "auto"),
                              "_isolate_network": config.get("isolate_network", True)}
                       for name, definition in merged_mcp_servers(config).items()}
        self.mcp = MCPManager(definitions, self.sandbox.root)
        self.logger = get_logger()
        self.pending_input: list[str] = []
        self._input_arrived = asyncio.Event()
        from .plugin_runtime import PluginRuntime
        self.plugin_runtime = PluginRuntime(session.id)
        self._turn_instructions = ""
        self._mcp_definitions = merged_mcp_servers(config)
        self._scoped_seen: set[str] = set()
        self._tool_cache: dict[str, tuple[str, bool, str, int]] = {}
        self._work_revision = 0

    def steer(self, text: str) -> None:
        self.pending_input.append(text)
        self._input_arrived.set()

    def _consume_input(self) -> bool:
        pending, self.pending_input = self.pending_input, []
        self._input_arrived.clear()
        if pending:
            self._tool_cache.clear()
            self._work_revision += 1
        for text in pending:
            self.session.add_user(text)
        return bool(pending)

    # setup

    def use(self, provider, provider_key: str, model: str) -> None:
        previous = self.provider
        self.provider = provider
        self.provider_key = provider_key
        self.model = model
        if previous is not None and previous is not provider:
            close = getattr(previous, "close", None)
            if close:
                try:
                    asyncio.get_running_loop().create_task(close())
                except RuntimeError:
                    pass

    def reload_skills(self) -> list[skills_mod.Skill]:
        self.skills = skills_mod.apply_config(skills_mod.discover(), self.config)
        return self.skills

    @property
    def ready(self) -> bool:
        return self.provider is not None and bool(self.model)

    def context_size(self) -> int:
        """Rough token count of the history."""
        return estimate_messages(self.session.messages)

    def context_is_heavy(self) -> bool:
        """True once the history is worth compacting."""
        configured = self.config.get("model_context_limits", {})
        model_limit = configured.get(self.model) if isinstance(configured, dict) else None
        try:
            model_warning = int(model_limit * 0.8) if model_limit else 0
        except (TypeError, ValueError):
            model_warning = 0
        limit = model_warning or int(self.config.get("context_warning", CONTEXT_WARNING)
                                     or CONTEXT_WARNING)
        return limit > 0 and self.context_size() > limit

    @property
    def retry_attempts(self) -> int:
        """Tries allowed for one provider call before the turn gives up."""
        try:
            wanted = int(self.config.get("retry_attempts", RETRY_ATTEMPTS))
        except (TypeError, ValueError):
            return RETRY_ATTEMPTS
        return max(1, min(wanted, 100))

    @property
    def iteration_limit(self) -> int:
        """Tool rounds allowed in one turn; 0 means no limit."""
        try:
            wanted = int(self.config.get("max_iterations", DEFAULT_ITERATIONS))
        except (TypeError, ValueError):
            return DEFAULT_ITERATIONS
        wanted = max(wanted, 0)
        profile = getattr(self.provider, "profile", None)
        if profile is not None:
            return min(wanted or profile.max_iterations, profile.max_iterations)
        return wanted

    @property
    def max_tokens(self) -> int:
        """Room the model gets for one reply."""
        try:
            wanted = int(self.config.get("max_tokens", DEFAULT_MAX_TOKENS)
                         or DEFAULT_MAX_TOKENS)
        except (TypeError, ValueError):
            return DEFAULT_MAX_TOKENS
        wanted = max(512, min(wanted, 200_000))
        profile = getattr(self.provider, "profile", None)
        if profile is not None:
            return min(wanted, profile.max_tokens)
        return wanted

    def system_prompt(self) -> str:
        extra = ""
        if self._turn_instructions:
            extra += "\n\nCurrent command instructions:\n" + self._turn_instructions
        extra += "\n\n" + self.plugin_runtime.block(self.config)
        return self._base_system_prompt() + extra

    def _base_system_prompt(self) -> str:
        active_skills = self.skills
        if self.plugin_runtime.ponytail_mode == "off":
            active_skills = [s for s in self.skills if s.name != "ponytail:ponytail"]
        if getattr(self.provider, "owns_context", False):
            # The CLI owns its tools and sandbox; contribute only host guidance
            # and enabled skills, without Eirene tool instructions.
            from .platforms import guidance
            return guidance(native=True) + "\n\n" + skills_mod.inline_block(active_skills)
        self.project = project_mod.discover(self.sandbox.root)
        text = prompts.build(sandbox=str(self.sandbox.root), mode=self.mode.value,
                             os_name={"Darwin": "macOS"}.get(self.host.system, self.host.system),
                             shell=self.host.shell, date=date.today().isoformat(), host=self.host)
        block = skills_mod.catalog_block(active_skills)
        if block:
            text = f"{text}\n{block}"
        project = self.project.prompt_block()
        if project:
            text = f"{text}\n\n{project}"
        plan = plan_mod.load(self.sandbox.root, self.session.id)
        if plan.active:
            text = f"{text}\n\nDurable session plan:\n{plan.render()}"
        return text

    def tool_specs(self) -> list[dict[str, Any]] | None:
        if (not self.provider or getattr(self.provider, "owns_context", False)
                or not self.provider.supports_tools):
            return None
        specs = tools.specs(include_exec=self.mode is not Mode.PLAN)
        if self.mode is Mode.PLAN:
            specs.extend(spec for spec in tools.specs() if spec["name"] == "run_command")
        if self.mode is not Mode.PLAN:
            specs.extend(self.mcp.specs())
        return self.host.tool_specs(specs)

    # the loop

    async def run(self, text: str, *, record_text: str | None = None
                  ) -> AsyncIterator[AgentEvent]:
        if not self.ready:
            yield Failed("no provider selected; run /connect")
            yield TurnDone(0.0, 0.0, Usage())
            return
        definitions = merged_mcp_servers(self.config)
        if definitions != self._mcp_definitions:
            await self.mcp.close()
            self._mcp_definitions = definitions
            self.mcp = MCPManager({name: {**definition,
                "_isolation": self.config.get("execution_isolation", "auto"),
                "_isolate_network": self.config.get("isolate_network", True)}
                for name, definition in definitions.items()}, self.sandbox.root)
        native_plugins = getattr(self.provider, "set_plugins", None)
        if native_plugins:
            native_plugins({} if self.mode is Mode.PLAN else definitions)
        if self.mode is Mode.PLAN or getattr(self.provider, "owns_context", False):
            await self.mcp.close()
        else:
            await self.mcp.ensure()
        self.session.repair_pending()
        self._consume_input()
        self._turn_instructions = text if record_text is not None and record_text != text else ""
        self.session.add_user(record_text if record_text is not None else text)
        self._tool_cache.clear()
        self._work_revision = 0
        self.logger.info("turn.started", extra={"session_id": self.session.id,
                                                "provider": self.provider_key,
                                                "model": self.model,
                                                "attachment_count": 0})
        started = time.monotonic()
        first_token = 0.0
        turn_usage = Usage()
        prepare = getattr(self.provider, "prepare_context", None)
        # Preparation happens inside the turn's error boundary below.
        local_context = 0
        limit = self.iteration_limit
        iteration = 0
        signatures: list[str] = []
        outcomes: list[str] = []
        redirected = False
        truncated_recoveries = 0
        status = "completed"

        try:
            for notice in await self.plugin_runtime.submit(
                    record_text if record_text is not None else text,
                    self.sandbox, self.config, plan=self.mode is Mode.PLAN):
                yield Notice(notice)
            if prepare:
                local_context = await prepare(self.model)
                limit = self.iteration_limit
            while True:
                async for event in self._background_completions():
                    yield event
                self._consume_input()
                if limit and iteration >= limit and local_context:
                    if len(outcomes) >= 2 and outcomes[-1] != outcomes[-2]:
                        yield Notice("continuing with another local model work batch", transient=True)
                        iteration = 0
                    elif not redirected:
                        self.session.add_assistant("Review the current objective and tool results. Continue with the next unfinished step; change approach if an action failed.")
                        redirected = True
                        iteration = 0
                    elif await self._recover_local("I need a different approach to finish this task."):
                        iteration = 0
                        signatures.clear()
                        outcomes.clear()
                    else:
                        status = "blocked"
                        yield Notice("waiting for input: continue, try a different approach, or switch models")
                        break
                if limit and iteration >= limit:
                    note = (f"stopped after {limit} steps; raise max_iterations "
                            "in the config, or set it to 0 for no limit")
                    self.session.add_note("guard", reason=note)
                    yield Notice(note)
                    status = "incomplete"
                    break
                iteration += 1
                yield Phase(THINKING)
                reply, calls, seen_text, usage_in, usage_out = "", [], False, 0, 0
                thinking = ""
                finish = ""

                async for event in self._budget_context():
                    yield event

                async for event in self._stream():
                    if isinstance(event, (Notice, Phase)):
                        yield event
                    elif isinstance(event, ThinkingDelta):
                        thinking += event.text
                        yield Thought(event.text)
                    elif isinstance(event, TextDelta):
                        if not seen_text:
                            seen_text = True
                            if not first_token:
                                first_token = time.monotonic() - started
                            yield Phase(ANSWERING)
                        reply += event.text
                        yield Answer(event.text)
                    elif isinstance(event, ToolCall):
                        calls.append(event)
                    elif isinstance(event, pbase.Usage):
                        usage_in = max(usage_in, event.input_tokens)
                        usage_out = max(usage_out, event.output_tokens)
                        yield Tokens(usage_in, usage_out)
                    elif isinstance(event, pbase.PlanUpdate):
                        yield PlanChanged(event.steps, event.explanation)
                    elif isinstance(event, pbase.ProviderTool):
                        # The provider already ran it; only show the work.
                        if event.finished:
                            output = artifacts.Writer()
                            output.feed(event.result)
                            output.close()
                            self.session.add_note("provider_tool", id=event.id, name=event.name,
                                label=event.label, finished=True, result=event.result[:24000],
                                is_error=event.is_error, artifact_id=output.id)
                            yield ToolFinished(event.id, event.name, event.label,
                                               event.result[:24000], event.is_error, 0.0, output.id)
                            continue
                        self.session.add_note("provider_tool", id=event.id, name=event.name,
                                              label=event.label, finished=False)
                        yield Phase(RUNNING if event.kind == tools.EXEC else
                                    (WRITING if event.kind == tools.WRITE
                                     else THINKING))
                        if event.preview:
                            yield ToolPreview(event.id, event.name, event.label,
                                              event.preview)
                        else:
                            yield ToolStarted(event.id, event.name, event.label,
                                              event.kind)
                    elif isinstance(event, Done):
                        finish = event.reason

                turn_usage.input_tokens += usage_in
                turn_usage.output_tokens += usage_out
                if not first_token:
                    first_token = time.monotonic() - started

                serialised = [self._serialise_call(c) for c in calls]
                self.session.add_assistant(reply, serialised, thinking)

                if finish in TRUNCATED:
                    note = ("the model ran out of room and was cut off; "
                            f"raise max_tokens (now {self.max_tokens}) in "
                            "the config, or ask for something smaller")
                    self.session.add_note("guard", reason=note)
                    yield Notice(note, transient=bool(local_context), phase="working")
                    if calls:
                        self.session.repair_pending("not executed: the tool request was cut off; retry with complete, smaller arguments")
                    if local_context and truncated_recoveries < 2:
                        truncated_recoveries += 1
                        self.session.add_assistant("The previous response was cut off. Continue exactly where it ended without repeating text. Any tool calls in that response were not executed; use smaller complete calls.")
                        continue
                    if calls:
                        status = "incomplete"
                        break

                if not calls:
                    from ..tools import processes
                    pending = processes.pending(self.sandbox.root, self.session.id)
                    if pending:
                        yield Phase(RUNNING)
                        yield Notice("waiting for background commands", transient=True, phase="running")
                        waits = [asyncio.create_task(p.done.wait()) for p in pending]
                        changed = asyncio.create_task(self._input_arrived.wait())
                        try:
                            all_done = asyncio.gather(*waits)
                            await asyncio.wait({all_done, changed}, return_when=asyncio.FIRST_COMPLETED)
                            if self.pending_input:
                                continue
                        finally:
                            changed.cancel()
                            all_done.cancel()
                            for wait in waits:
                                wait.cancel()
                            await asyncio.gather(all_done, changed, *waits, return_exceptions=True)
                        continue
                    if self.pending_input:
                        continue
                    if finish in TRUNCATED or finish in {"cancelled", "interrupted", "failed", "incomplete"}:
                        status = "incomplete"
                    break

                signature = _signature(calls)
                signatures.append(signature)
                del signatures[:-3]
                if (signatures[-3:].count(signature) >= 3 and len(outcomes) >= 2
                        and outcomes[-1] == outcomes[-2]
                        and not all(c.name == "poll_process" for c in calls)):
                    note = "stopped: the same tool call repeated three times"
                    self.session.add_note("guard", reason=note)
                    yield Notice(note, transient=bool(local_context), phase="adjusting approach")
                    self.session.repair_pending("not executed: repeated-call guard stopped the turn")
                    if local_context and not redirected:
                        self.session.add_assistant("That action already ran. Use its recorded result. Choose a different action that advances the unfinished task, or explain the specific blocker without repeating the action.")
                        redirected = True
                        signatures.clear()
                        outcomes.clear()
                        iteration = 0
                        continue
                    if local_context and await self._recover_local("The same action keeps producing the same result."):
                        signatures.clear()
                        outcomes.clear()
                        iteration = 0
                        continue
                    status = "incomplete"
                    break

                stop = False
                batch_results = []
                async for event in self._dispatch(calls):
                    if isinstance(event, ToolFinished):
                        batch_results.append((event.name, event.result.split("[output artifact:")[0], event.is_error))
                    if isinstance(event, Notice) and event.text in (_ABORT, _BLOCKED):
                        stop = True
                        status = "blocked" if event.text == _BLOCKED else "cancelled"
                    else:
                        yield event
                outcomes.append(json.dumps(sorted(batch_results), default=str))
                del outcomes[:-2]
                if stop:
                    yield Notice("waiting for required user input" if status == "blocked" else "stopped by you")
                    break

        except asyncio.CancelledError:
            from ..tools import processes
            await asyncio.gather(*(processes.stop(p.id)
                                   for p in processes.pending(self.sandbox.root, self.session.id)
                                   if p.running))
            self.session.repair_pending()
            self._consume_input()
            self.session.add_note("cancelled")
            self.logger.info("turn.cancelled", extra={"session_id": self.session.id})
            raise
        except (ProviderError, EireneError) as exc:
            status = "failed"
            self.session.repair_pending()
            self.session.add_note("error", message=str(exc))
            yield Failed(exc.user_message())
            self.logger.error("turn.failed", extra={"session_id": self.session.id,
                                                    "error_type": type(exc).__name__,
                                                    "error": str(exc)[:500]})
        except Exception as exc:  # noqa: BLE001
            status = "failed"
            self.session.repair_pending()
            self.session.add_note("error", message=repr(exc))
            yield Failed(f"unexpected failure: {exc}")
            self.logger.exception("turn.crashed", extra={"session_id": self.session.id})

        seconds = time.monotonic() - started
        self.usage.record(turn_usage.input_tokens, turn_usage.output_tokens,
                          seconds, self.model)
        self.logger.info("turn.finished", extra={"session_id": self.session.id,
                                                 "seconds": seconds,
                                                 "input_tokens": turn_usage.input_tokens,
                                                 "output_tokens": turn_usage.output_tokens})
        self.session.add_note("turn_status", status=status)
        yield TurnDone(seconds, first_token, turn_usage, status)

    async def _budget_context(self):
        if getattr(self.provider, "owns_context", False):
            return
        from .usage import estimate_tokens
        from .compact import compact
        limits = self.config.get("model_context_limits", {})
        hard = int(limits.get(self.model, 0) or 0)
        prepare = getattr(self.provider, "prepare_context", None)
        local = await prepare(self.model) if prepare else 0
        if local:
            hard = min(hard, local) if hard else local
        overhead = estimate_tokens(self.system_prompt()) + estimate_tokens(json.dumps(self.tool_specs()))
        if local:
            profile = self.provider.profile
            overhead = estimate_tokens(profile.system(self.system_prompt())) + estimate_tokens(json.dumps(profile.tools(self.tool_specs())))
        reserve = self.max_tokens + (256 if local else 2048)
        threshold = int(self.config.get("context_warning", CONTEXT_WARNING) or CONTEXT_WARNING)
        budget = min(threshold, hard - reserve) if hard else threshold
        if budget <= 0:
            raise ProviderError("instructions, tools and response allowance exceed the model context budget")
        if self.context_size() + overhead <= budget:
            return
        if not self.config.get("auto_compact", True):
            raise ProviderError("context budget reached; use /compact or enable auto_compact")
        yield Notice("preparing conversation memory", transient=True, phase="working")
        before, after, _ = await compact(self.session, self.provider, self.model,
            target_tokens=budget - overhead if local else None, context_tokens=hard or None,
            automatic=True)
        self.session.add_note("context_compacted", before=before, after=after)
        yield Notice(f"context compacted {before} → {after} estimated tokens", transient=True)
        if self.context_size() + overhead > budget:
            raise ProviderError("context still exceeds budget after compaction; reduce tool output or response allowance")

    async def _dispatch(self, calls):
        parallel_names = {"read_file", "list_dir", "glob", "search_text", "find_symbol", "find_references", "read_output"}
        unique = len({fingerprint(c.name, c.arguments) for c in calls}) == len(calls)
        parallel = len(calls) > 1 and unique and not any(merged_hooks(self.config).values()) and all(
            c.name in parallel_names and not tools.sandbox_escape(c.name, c.arguments, self.sandbox)
            for c in calls)
        if parallel and not self.pending_input:
            queue = asyncio.Queue(maxsize=64)
            semaphore = asyncio.Semaphore(max(1, min(4, self.host.cpu_threads)))
            async def worker(call):
                async with semaphore:
                    async for event in self._handle(call, output_share=len(calls)):
                        await queue.put(event)
            tasks = [asyncio.create_task(worker(c)) for c in calls]
            try:
                while any(not t.done() for t in tasks) or not queue.empty():
                    try:
                        yield await asyncio.wait_for(queue.get(), 0.05)
                    except asyncio.TimeoutError:
                        pass
                await asyncio.gather(*tasks)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            return
        stopped = False
        for call in calls:
            if stopped or self.pending_input:
                self.session.add_tool_result(call.id, call.name,
                    "not executed: turn stopped or new user input arrived; reconsider action", True)
                continue
            async for event in self._handle(call):
                if isinstance(event, Notice) and event.text in (_ABORT, _BLOCKED):
                    stopped = True
                yield event

    async def _recover_local(self, reason: str) -> bool:
        """Keep recovery explicit when a local model cannot make progress."""
        options = ["Try a different approach", "Continue", "Pause and switch models"]
        self.session.add_note("recovery", reason=reason, options=options)
        if self.choose is None:
            return False
        answer = await self.choose(reason, options)
        if answer not in options[:2]:
            return False
        self.session.add_user(f"{answer}. Review the current goal and results; avoid repeating unsuccessful actions.")
        return True

    async def _stream(self):
        """Ride out a provider that is briefly unreachable."""
        attempts = self.retry_attempts
        delay = RETRY_DELAY
        attempt = 0
        while True:
            attempt += 1
            produced = False
            waiting = attempt > 1
            try:
                async for event in self._stream_once():
                    if isinstance(event, (Notice, pbase.ConnectionStatus)):
                        waiting = True
                    elif waiting:
                        yield Phase(ANSWERING if isinstance(event, TextDelta) else THINKING)
                        waiting = False
                    if not isinstance(event, (Notice, pbase.ConnectionStatus, pbase.Usage)):
                        produced = True
                    if isinstance(event, pbase.ConnectionStatus):
                        yield Notice(event.text, transient=True, phase="reconnecting")
                    else:
                        yield event
                return
            except ProviderError as exc:
                if produced or not exc.retryable:
                    raise
                if attempt == attempts:
                    if getattr(self.provider, "profile", None) is not None and await self._recover_local(exc.user_message()):
                        attempt = 0
                        delay = RETRY_DELAY
                        continue
                    raise ProviderError(f"{exc.user_message()}. You can continue later, try a different approach, or switch models.") from exc
                wait = max(0.0, float(getattr(exc, "retry_after", None) or min(delay, RETRY_MAX_DELAY)))
                self.logger.info("provider.retry",
                                 extra={"session_id": self.session.id,
                                        "attempt": attempt, "wait": wait,
                                        "error": str(exc)[:200]})
                yield Notice(f"{exc.user_message()} - retrying in "
                             f"{wait:.0f}s (attempt {attempt + 1} of {attempts})",
                             transient=True, phase="reconnecting")
                remaining = wait
                while remaining > 0:
                    step = min(1.0, remaining)
                    await asyncio.sleep(step)
                    remaining -= step
                    if remaining > 0:
                        yield Notice(f"Connection interrupted; retrying in {remaining:.0f}s (attempt {attempt + 1} of {attempts})",
                                     transient=True, phase="reconnecting")
                delay = min(delay * 2, RETRY_MAX_DELAY)

    async def _stream_once(self):
        """One provider call."""
        assert self.provider is not None
        configure = getattr(self.provider, "set_context", None)
        if configure:
            configure(self.sandbox.root, self.mode.value, self.approve, self.choose)
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        sentinel = object()

        async def pump():
            try:
                async for event in self.provider.stream(
                        list(self.session.messages), self.model,
                        system=self.system_prompt(), tools=self.tool_specs(),
                        max_tokens=self.max_tokens):
                    await queue.put(event)
            except asyncio.CancelledError:
                raise
            except BaseException as exc:  # noqa: BLE001
                await queue.put(exc)
            else:
                await queue.put(sentinel)

        task = asyncio.create_task(pump())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), CONNECTION_STATUS_AFTER)
                except asyncio.TimeoutError:
                    yield Notice("Waiting for provider response; connection may be slow", transient=True,
                                 phase="waiting for response")
                    continue
                if item is sentinel:
                    break
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            if not task.done():
                task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def _handle(self, call: ToolCall, *, output_share: int = 1) -> AsyncIterator[AgentEvent]:
        try:
            async for event in self._handle_checked(call, output_share=output_share):
                yield event
        except (ToolError, SandboxError) as exc:
            result = f"Call not executed: {exc.user_message()}. Correct the request before continuing."
            self.session.add_tool_result(call.id, call.name, result, True)
            yield Notice(result, transient=True, phase="adjusting approach")

    async def _handle_checked(self, call: ToolCall, *, output_share: int = 1) -> AsyncIterator[AgentEvent]:
        """Approve and execute one tool call."""
        if call.name == "ask_user" and isinstance(call.arguments, dict):
            # Missing choices still represents required user input, not license
            # to let the model proceed without an answer.
            call.arguments.setdefault("options", [])
        try:
            if not self.mcp.owns(call.name):
                tools.validate_arguments(call.name, call.arguments)
        except ToolError as exc:
            result = f"Call not executed: {exc.user_message()}. Correct the arguments before continuing."
            self.session.add_tool_result(call.id, call.name, result, True)
            yield Notice(result, transient=True, phase="adjusting approach")
            return
        if call.name == "ask_user":
            async for event in self._ask_user(call):
                yield event
            return
        result_limit = min(await self._tool_output_limit(output_share), max(512, 12000 // output_share))
        is_mcp = self.mcp.owns(call.name)
        self.session.add_note("tool_state", call_id=call.id, tool=call.name, state="requested")
        kind = tools.EXEC if is_mcp else tools.kind_of(call.name)
        if call.name == "run_command" and tools.harmless(call.name, call.arguments):
            kind = tools.READ
        label = call.name if is_mcp else tools.describe(call.name, call.arguments, self.sandbox)
        key = fingerprint(call.name, call.arguments)
        cached = self._tool_cache.get(key)
        # Dynamic process and network observations must remain fresh. Changes
        # invalidate local observations; a new user turn starts a fresh ledger.
        cacheable = call.name in {
            "read_file", "list_dir", "glob", "search_text", "read_output",
            "write_file", "edit_file", "apply_patch", "run_command", "start_process",
        }
        from ..tools import processes
        if (cacheable and cached and cached[3] == self._work_revision
                and not processes.running() and not any(merged_hooks(self.config).values())):
            result, is_error, artifact_id, _ = cached
            result = compact_output(result, result_limit, artifact_id)
            recorded = compact_output(
                "Already attempted with these arguments; not executed again. Use this recorded result "
                "and take the next unfinished step or change the failed approach.\n" + result,
                result_limit, artifact_id)
            self.session.add_tool_result(call.id, call.name, recorded,
                                         is_error, artifact_id=artifact_id)
            yield ToolFinished(call.id, call.name, label, result, is_error, 0.0,
                               artifact_id, reused=True)
            return
        paths = tools.escape_paths(call.name, call.arguments) if call.name in CHANGE_TOOLS else []
        instruction_parts = []
        for path in paths:
            target = (self.sandbox.root / path).expanduser().resolve()
            block = project_mod.scoped_instructions(self.sandbox.root, target)
            if block and block not in self._scoped_seen:
                self._scoped_seen.add(block)
                instruction_parts.append(block)
        if instruction_parts:
            result = "Read these scoped instructions before retrying the edit:\n" + "\n".join(instruction_parts)
            self.session.add_tool_result(call.id, call.name, result)
            yield ToolFinished(call.id, call.name, label, result, False, 0.0)
            return
        escape = ("external MCP tool requires explicit approval" if is_mcp else
                  tools.sandbox_escape(call.name, call.arguments, self.sandbox))
        network_tools = {"web_search", "web_fetch", "http_request", "browser_inspect", "browser_interact", "browser_screenshot"}
        if call.name in network_tools and self.config.get("isolate_network", True):
            escape = escape or "this tool requires network access outside command isolation"
        native_windows = (platform.system() == "Windows" and
                          self.config.get("execution_isolation", "auto") == "auto" and
                          call.name in {"run_command", "start_process", "language_diagnostics"})
        if native_windows:
            escape = "Windows native execution has no kernel filesystem or network isolation; approve this command with your user account's access"
        verdict, reason = decide(self.mode, kind, escape)
        if native_windows and self.mode is Mode.PLAN:
            verdict, reason = BLOCK, "native Windows commands cannot enforce plan mode; use portable file/search tools"
        if verdict != BLOCK and not escape and tools.harmless(call.name, call.arguments):
            verdict, reason = ALLOW, ""
        outside = tools.escape_paths(call.name, call.arguments) if escape else []
        if verdict == ASK and escape and self.approve is None:
            verdict = BLOCK
            reason = f"{reason}; no one is here to approve leaving it"

        preview = ""
        if call.name in CHANGE_TOOLS:
            with self.sandbox.permit(*outside):
                preview = tools.preview(call.name, call.arguments, self.sandbox)
            if preview:
                yield ToolPreview(call.id, call.name, label, preview)

        if verdict == BLOCK:
            self.session.add_note("tool_state", call_id=call.id, state="blocked")
            message = f"blocked: {reason}"
            self.session.add_tool_result(call.id, call.name, message, True)
            yield ToolFinished(call.id, call.name, label, message, True, 0.0)
            return

        if verdict == ASK and (escape or call.name not in self.always):
            yield Phase(WAITING)
            answer = await self._ask(call, label, reason, preview)
            if answer == ALWAYS:
                # "always" covers a tool, never a standing exit from the sandbox.
                if not escape:
                    self.always.add(call.name)
            elif answer != YES:
                self.session.add_note("tool_state", call_id=call.id, state="denied")
                message = "denied by the user"
                self.session.add_tool_result(call.id, call.name, message, True)
                yield ToolFinished(call.id, call.name, label, message, True, 0.0)
                yield Notice(_ABORT)
                return

        yield Phase(RUNNING if kind == tools.EXEC else
                    (WRITING if kind == tools.WRITE else THINKING))
        yield ToolStarted(call.id, call.name, label, kind)
        self.session.add_note("tool_state", call_id=call.id, tool=call.name,
                              state="started", approved=True)
        output = artifacts.Writer()
        yield ToolOutput(call.id, "", output.id)
        started = time.monotonic()
        try:
            hooks_enabled = self.mode is not Mode.PLAN
            before_hooks = (await hook_mod.run("before_tool", call.name, self.sandbox,
                                               self.config) if hooks_enabled else [])
            if before_hooks:
                yield Notice(f"ran {len(before_hooks)} before-tool hook(s)", transient=True)
            if is_mcp:
                result = await self.mcp.call(call.name, call.arguments)
            else:
                if call.name == "load_skill":
                    wanted = str(call.arguments.get("name") or "")
                    selected = next((skill for skill in self.skills
                                     if skill.name == wanted), None)
                    if selected is None or not selected.enabled:
                        raise ToolError(f"skill '{wanted}' is disabled or unavailable")
                with self.sandbox.permit(*outside):
                    async for item in self._execute_live(call,
                        call.name, call.arguments, self.sandbox,
                        timeout=float(self.config.get("shell_timeout", 120) or 120),
                        max_bytes=min(result_limit, int(self.config.get("max_output_bytes", 200_000) or 200_000)),
                        output=output,
                        isolation="none" if native_windows else str(self.config.get("execution_isolation", "auto")),
                        isolate_network=bool(self.config.get("isolate_network", True)) and call.name not in network_tools,
                        plan_scope=self.session.id,
                        read_only=(self.mode is Mode.PLAN or kind == tools.READ) and not native_windows):
                        if isinstance(item, ToolOutput):
                            yield item
                        else:
                            result = item
            is_error = False
        except asyncio.CancelledError:
            output.close()
            self.session.add_tool_result(call.id, call.name,
                "interrupted; outcome unknown, inspect state before retrying", True,
                artifact_id=output.id)
            self.session.add_note("tool_state", call_id=call.id, state="outcome_unknown")
            raise
        except (ToolError, EireneError) as exc:
            result, is_error = exc.user_message(), True
        except Exception as exc:  # noqa: BLE001
            result, is_error = f"tool failed: {exc}", True

        try:
            after_hooks = (await hook_mod.run("after_tool", call.name, self.sandbox,
                                              self.config, failed=is_error)
                           if hooks_enabled else [])
            if after_hooks:
                yield Notice(f"ran {len(after_hooks)} after-tool hook(s)", transient=True)
        except (ToolError, EireneError) as exc:
            result = f"{result}\nafter_tool hook failed: {exc.user_message()}"
            is_error = True
        except BaseException:
            output.close()
            raise

        seconds = time.monotonic() - started
        if output.size == 0 or is_error:
            output.feed(result)
        output.close()
        # Every tool, including MCP and artifact pages, shares the same budget.
        # Recompute after execution because parallel peers may have added history.
        result_limit = min(result_limit, await self._tool_output_limit(output_share))
        result = compact_output(result, result_limit, output.id,
                                prefix_only=call.name in {"read_file", "read_output", "web_search"},
                                source_required=output.size > len(result.encode("utf-8")))
        if kind in (tools.WRITE, tools.EXEC):
            # Even failed commands can partially change state.
            self._work_revision += 1
        if cacheable and not processes.running():
            self._tool_cache[key] = (result, is_error, output.id, self._work_revision)
            if len(self._tool_cache) > 128:
                self._tool_cache.pop(next(iter(self._tool_cache)))
        vision_image = None
        if call.name == "read_image" and not is_error:
            try:
                from .attachments import prepare_image
                vision_image = prepare_image(
                    self.sandbox, str(call.arguments.get("path") or ""))
            except EireneError as exc:
                result = f"{result}\nvision payload failed: {exc.user_message()}"
                is_error = True
        self.session.add_tool_result(call.id, call.name, result, is_error, seconds, output.id)
        self.session.add_note("tool_state", call_id=call.id,
                              state="failed" if is_error else "succeeded", artifact_id=output.id)
        if vision_image:
            self.session.add_user(
                f"Image content loaded from {call.arguments.get('path')}.", [vision_image])
        self.logger.info("tool.finished", extra={"session_id": self.session.id,
                                                 "tool": call.name,
                                                 "seconds": seconds,
                                                 "failed": is_error})
        yield ToolFinished(call.id, call.name, label, result, is_error, seconds, output.id)

    async def _local_output_limit(self) -> int:
        return await self._tool_output_limit()

    async def _tool_output_limit(self, share: int = 1) -> int:
        """Bound all observations by context left after instructions and reply."""
        from .usage import estimate_tokens
        profile = getattr(self.provider, "profile", None)
        context = int(self.config.get("model_context_limits", {}).get(self.model, 0) or 0)
        prepare = getattr(self.provider, "prepare_context", None)
        if profile:
            local = await prepare(self.model) if prepare else profile.context_tokens
            context = min(context, local) if context else local
            system = profile.system(self.system_prompt())
            specs = profile.tools(self.tool_specs())
            ceiling = min(12000, profile.context_tokens // 2)
        else:
            system, specs = self.system_prompt(), self.tool_specs()
            ceiling = 12000
        overhead = estimate_tokens(system) + estimate_tokens(json.dumps(specs))
        threshold = int(self.config.get("context_warning", CONTEXT_WARNING) or CONTEXT_WARNING)
        budget = min(threshold, context - self.max_tokens - (256 if profile else 2048)) if context else threshold
        available = max(0, budget - overhead - self.context_size() - 64 * share)
        return min(ceiling, available * 4 // max(1, share))

    async def _background_completions(self):
        from ..tools import processes
        completed = [item for item in processes.pending(self.sandbox.root, self.session.id)
                     if not item.running]
        if not completed:
            return
        remaining = await self._tool_output_limit()
        for item in completed:
            result = await processes.poll(item.id, all_output=True)
            call_id = "background_" + item.id
            self.session.add_assistant("", [{"id": call_id, "name": "poll_process", "arguments": {"process_id": item.id}}])
            limit = min(remaining, await self._tool_output_limit())
            result = compact_output(result, limit, item.artifact.id,
                                    source_required=True)
            remaining -= len(result)
            self.session.add_tool_result(call_id, "poll_process", result, item.state != "succeeded",
                                         artifact_id=item.artifact.id)
            item.notified = True
            self._tool_cache.clear()
            self._work_revision += 1
            yield ToolFinished(item.call_id or call_id, "run_command", item.command,
                result, item.state != "succeeded", time.monotonic() - item.started,
                item.artifact.id)

    async def _execute_live(self, call, name, arguments, sandbox, *, output, **kwargs):
        queue: asyncio.Queue = asyncio.Queue(maxsize=32)

        def feed(chunk):
            output.feed(chunk)
            try:
                queue.put_nowait(chunk)
            except asyncio.QueueFull:
                pass  # The complete bounded artifact remains available.

        if name in {"web_search", "web_fetch"}:
            kwargs["search_service"] = self.search_service
        task = asyncio.create_task(tools.execute(name, arguments, sandbox, on_output=feed, call_id=call.id, **kwargs))
        try:
            while not task.done() or not queue.empty():
                try:
                    chunk = await asyncio.wait_for(queue.get(), 0.05)
                    yield ToolOutput(call.id, chunk)
                except asyncio.TimeoutError:
                    pass
            yield await task
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _serialise_call(self, call: ToolCall) -> dict[str, Any]:
        """Keep enough presentation data to redraw tool activity on resume."""
        record: dict[str, Any] = {"id": call.id, "name": call.name,
                                  "arguments": call.arguments}
        try:
            if not self.mcp.owns(call.name):
                tools.validate_arguments(call.name, call.arguments)
        except ToolError:
            return record
        label = tools.describe(call.name, call.arguments, self.sandbox)
        if label:
            record["label"] = label
        if call.name in CHANGE_TOOLS:
            try:
                preview = tools.preview(call.name, call.arguments, self.sandbox)
            except EireneError:
                return record
            if preview:
                record["preview"] = preview
                path = tools.touched_path(call.name, call.arguments)
                if path:
                    try:
                        exists = self.sandbox.resolve(path).exists()
                    except EireneError:
                        exists = True
                    record["action"] = "Update" if exists else "Create"
        return record

    async def close(self) -> None:
        await self.mcp.close()
        close = getattr(self.provider, "close", None)
        if close:
            await close()

    async def _ask_user(self, call: ToolCall) -> AsyncIterator[AgentEvent]:
        """Put the model's question to the user as a choice."""
        question = str(call.arguments.get("question", "")).strip() or "which one?"
        raw = call.arguments.get("options") or []
        options = [str(item).strip() for item in raw if str(item).strip()][:6]
        if not options or self.choose is None:
            message = "no one is here to answer; blocked pending user input"
            self.session.add_tool_result(call.id, call.name, message, False)
            yield ToolFinished(call.id, call.name, question, message, False, 0.0)
            yield Notice(_BLOCKED)
            return

        yield Phase(WAITING)
        try:
            answer = await self.choose(question, options)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            answer = None

        if answer is None or answer == tools.CHAT_OPTION:
            message = "the user wants to talk it through before deciding"
            self.session.add_tool_result(call.id, call.name, message, False)
            yield ToolFinished(call.id, call.name, question, message, False, 0.0)
            yield Notice("say what you think and it will carry on from there")
            yield Notice(_ABORT)
            return

        self.session.add_tool_result(call.id, call.name, answer, False)
        yield ToolFinished(call.id, call.name, question, answer, False, 0.0)

    async def _ask(self, call: ToolCall, label: str, reason: str,
                   preview: str = "") -> str:
        if self.approve is None:
            return YES
        preview = preview or tools.preview(call.name, call.arguments, self.sandbox)
        try:
            answer = await self.approve(call.name, label, preview, reason)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            return NO
        return answer if answer in (YES, NO, ALWAYS) else NO

    # side channel

    async def aside(self, question: str) -> AsyncIterator[str]:
        """Answer with the chat in view, without touching it."""
        if not self.ready:
            raise ProviderError("no provider selected; run /connect")
        history = list(self.session.messages)[-ASIDE_HISTORY:]
        history.append(Message.user(question))
        stream = getattr(self.provider, "isolated_stream", self.provider.stream)
        async for event in stream(history, self.model, system=prompts.BTW_PROMPT,
                                  tools=None, max_tokens=2048):
            if isinstance(event, TextDelta):
                yield event.text

    async def options_for(self, question: str) -> list[str]:
        """Ask the model to turn its own question into choices."""
        if not self.ready:
            return []
        parts: list[str] = []
        stream = getattr(self.provider, "isolated_stream", self.provider.stream)
        async for event in stream(
                [Message.user(question[-1500:])], self.model,
                system=prompts.OPTIONS_PROMPT, tools=None,
                max_tokens=TITLE_TOKENS):
            if isinstance(event, TextDelta):
                parts.append(event.text)
        lines = [questions._clean(line) for line in "".join(parts).splitlines()]
        picked = [line for line in lines if line and len(line) < 80]
        return picked[:questions.MAX_OPTIONS]

    async def suggest_prompt(self, request: str, reply: str) -> str:
        """Generate a draft only; never run tools or add it to conversation history."""
        if not self.ready:
            return ""
        stream = getattr(self.provider, "isolated_stream", self.provider.stream)
        parts = []
        truncated = False
        exchange = json.dumps({"previous_user_message": request[:4000],
                               "assistant_reply_so_far": reply[-8000:]}, ensure_ascii=False)
        async for event in stream([Message.user(exchange)],
                                  self.model, tools=None, max_tokens=1024,
                                  system=prompts.SUGGESTION_PROMPT):
            if isinstance(event, TextDelta):
                parts.append(event.text)
            elif isinstance(event, Done) and event.reason in {"length", "max_tokens", "max_output_tokens"}:
                truncated = True
        suggestion = " ".join("".join(parts).strip().split()).strip('"“”')
        # Never turn a token-limit fragment into a visible prompt, or slice a
        # sentence in the middle just to fit the composer.
        from .suggestions import is_assistant_reply
        if (truncated or len(suggestion) > 240 or len(suggestion.split()) > 30
                or not suggestion.endswith((".", "?", "!", "。", "？", "！"))
                or is_assistant_reply(suggestion)):
            return ""
        return suggestion

    async def title(self, request: str, reply: str = "") -> str:
        """Ask the model to name this session."""
        if not self.ready:
            return ""
        body = f"Request:\n{request[:1500]}"
        if reply.strip():
            body += f"\n\nWhat happened:\n{reply[:600]}"
        parts: list[str] = []
        stream = getattr(self.provider, "isolated_stream", self.provider.stream)
        async for event in stream([Message.user(body)], self.model,
                                  system=prompts.TITLE_PROMPT, tools=None,
                                  max_tokens=TITLE_TOKENS):
            if isinstance(event, TextDelta):
                parts.append(event.text)
        return "".join(parts)


_ABORT = "\x00abort"
_BLOCKED = "\x00blocked"


def _signature(calls: list[ToolCall]) -> str:
    payload = [[c.name, sorted((c.arguments or {}).items(), key=lambda kv: kv[0])]
               for c in calls]
    try:
        return json.dumps(payload, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return repr(payload)


def _os_name() -> str:
    system = platform.system()
    return {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}.get(system, system)


def _shell_name() -> str:
    from .platforms import shell_name
    return shell_name()
