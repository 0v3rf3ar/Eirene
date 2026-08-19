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
from .errors import Cancelled, EireneError, ProviderError, ToolError
from .modes import ALLOW, ASK, BLOCK, Mode, decide
from .session import Message, Session
from .usage import Usage, estimate_messages
from . import git as git_ops
from . import project as project_mod
from . import hooks as hook_mod
from .mcp import MCPManager
from .plugins import merged_hooks, merged_mcp_servers
from . import plans as plan_mod
from .logging import get as get_logger

CHANGE_TOOLS = ("write_file", "edit_file", "apply_patch")
CONTEXT_WARNING = 60_000
ASIDE_HISTORY = 40
# Reasoning models spend tokens thinking before they answer.
TITLE_TOKENS = 1024
TRUNCATED = ("length", "max_tokens", "max_output_tokens")
DEFAULT_MAX_TOKENS = 16384
RETRY_ATTEMPTS = 5
RETRY_DELAY = 1.0
RETRY_MAX_DELAY = 30.0
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


@dataclass
class ToolFinished:
    id: str
    name: str
    label: str
    result: str
    is_error: bool
    seconds: float


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


@dataclass
class Failed:
    text: str


@dataclass
class TurnDone:
    seconds: float
    thinking_seconds: float
    usage: Usage = field(default_factory=Usage)


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
        self.mode = Mode(config.mode) if config.mode in Mode._value2member_map_ else Mode.MANUAL
        self.provider = None
        self.provider_key = ""
        self.model = ""
        self.usage = Usage()
        self.skills: list[skills_mod.Skill] = []
        self.approve: ApprovalFn | None = None
        self.choose: ChoiceFn | None = None
        self.always: set[str] = set()
        self.turn_checkpoint = ""
        self.project = project_mod.discover(self.sandbox.root)
        self.mcp = MCPManager(merged_mcp_servers(config), self.sandbox.root)
        self.logger = get_logger()

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
        return max(1, min(wanted, 10))

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
        if getattr(self.provider, "owns_context", False):
            # The CLI brings its own prompt, tools and sandbox. Only skills
            # are Eirene's to contribute.
            return skills_mod.inline_block(self.skills)
        text = prompts.build(sandbox=str(self.sandbox.root), mode=self.mode.value,
                             os_name=_os_name(), shell=_shell_name(),
                             date=date.today().isoformat())
        block = skills_mod.catalog_block(self.skills)
        if block:
            text = f"{text}\n{block}"
        project = self.project.prompt_block()
        if project:
            text = f"{text}\n\n{project}"
        plan = plan_mod.load(self.sandbox.root)
        if plan.active:
            text = f"{text}\n\nDurable project plan:\n{plan.render()}"
        return text

    def tool_specs(self) -> list[dict[str, Any]] | None:
        if not self.provider or not self.provider.supports_tools:
            return None
        specs = tools.specs(include_exec=self.mode is not Mode.PLAN)
        if self.mode is Mode.AUTO:
            specs = [spec for spec in specs if spec["name"] != "ask_user"]
        if self.mode is not Mode.PLAN:
            specs.extend(self.mcp.specs())
        return specs

    # the loop

    async def run(self, text: str, *, record_text: str | None = None
                  ) -> AsyncIterator[AgentEvent]:
        if not self.ready:
            yield Failed("no provider selected; run /connect")
            yield TurnDone(0.0, 0.0, Usage())
            return
        await self.mcp.ensure()
        self.session.add_user(record_text if record_text is not None else text)
        self.logger.info("turn.started", extra={"session_id": self.session.id,
                                                "provider": self.provider_key,
                                                "model": self.model,
                                                "attachment_count": 0})
        started = time.monotonic()
        first_token = 0.0
        turn_usage = Usage()
        limit = self.iteration_limit
        iteration = 0
        signatures: list[str] = []
        self.turn_checkpoint = ""

        try:
            while True:
                if limit and iteration >= limit:
                    note = (f"stopped after {limit} steps; raise max_iterations "
                            "in the config, or set it to 0 for no limit")
                    self.session.add_note("guard", reason=note)
                    yield Notice(note)
                    break
                iteration += 1
                yield Phase(THINKING)
                reply, calls, seen_text, usage_in, usage_out = "", [], False, 0, 0
                thinking = ""
                finish = ""

                async for event in self._stream():
                    if isinstance(event, Notice):
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
                            yield ToolFinished(event.id, event.name, event.label,
                                               event.result, event.is_error, 0.0)
                            continue
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
                    yield Notice(note)

                if not calls:
                    break

                signature = _signature(calls)
                signatures.append(signature)
                if signatures[-3:].count(signature) >= 3:
                    note = "stopped: the same tool call repeated three times"
                    self.session.add_note("guard", reason=note)
                    yield Notice(note)
                    break

                stop = False
                for call in calls:
                    if stop:
                        self.session.add_tool_result(call.id, call.name,
                                                     "skipped, the turn was stopped", True)
                        continue
                    async for event in self._handle(call):
                        if isinstance(event, Notice) and event.text == _ABORT:
                            stop = True
                        else:
                            yield event
                if stop:
                    yield Notice("stopped by you")
                    break

        except asyncio.CancelledError:
            self.session.add_note("cancelled")
            self.logger.info("turn.cancelled", extra={"session_id": self.session.id})
            raise
        except (ProviderError, EireneError) as exc:
            self.session.add_note("error", message=str(exc))
            yield Failed(exc.user_message())
            self.logger.error("turn.failed", extra={"session_id": self.session.id,
                                                    "error_type": type(exc).__name__,
                                                    "error": str(exc)[:500]})
        except Exception as exc:  # noqa: BLE001
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
        yield TurnDone(seconds, first_token, turn_usage)

    async def _stream(self):
        """Ride out a provider that is briefly unreachable."""
        attempts = self.retry_attempts
        delay = RETRY_DELAY
        for attempt in range(1, attempts + 1):
            produced = False
            try:
                async for event in self._stream_once():
                    produced = True
                    yield event
                return
            except ProviderError as exc:
                if produced or not exc.retryable or attempt == attempts:
                    raise
                wait = min(float(getattr(exc, "retry_after", None) or delay),
                           RETRY_MAX_DELAY)
                self.logger.info("provider.retry",
                                 extra={"session_id": self.session.id,
                                        "attempt": attempt, "wait": wait,
                                        "error": str(exc)[:200]})
                yield Notice(f"{exc.user_message()} - retrying in "
                             f"{wait:.0f}s (attempt {attempt + 1} of {attempts})")
                await asyncio.sleep(wait)
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
            except BaseException as exc:  # noqa: BLE001
                await queue.put(exc)
            finally:
                await queue.put(sentinel)

        task = asyncio.create_task(pump())
        try:
            while True:
                item = await queue.get()
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

    async def _handle(self, call: ToolCall) -> AsyncIterator[AgentEvent]:
        """Approve and execute one tool call."""
        if call.name == "ask_user":
            async for event in self._ask_user(call):
                yield event
            return
        is_mcp = self.mcp.owns(call.name)
        kind = tools.EXEC if is_mcp else tools.kind_of(call.name)
        label = call.name if is_mcp else tools.describe(call.name, call.arguments, self.sandbox)
        escape = ("external MCP tool requires explicit approval" if is_mcp else
                  tools.sandbox_escape(call.name, call.arguments, self.sandbox))
        verdict, reason = decide(self.mode, kind, escape)
        if not escape and tools.harmless(call.name, call.arguments):
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
                message = "denied by the user"
                self.session.add_tool_result(call.id, call.name, message, True)
                yield ToolFinished(call.id, call.name, label, message, True, 0.0)
                yield Notice(_ABORT)
                return

        yield Phase(RUNNING if kind == tools.EXEC else
                    (WRITING if kind == tools.WRITE else THINKING))
        yield ToolStarted(call.id, call.name, label, kind)

        chunks: list[str] = []
        started = time.monotonic()
        try:
            hooks_enabled = self.mode is not Mode.PLAN
            has_hooks = hooks_enabled and any(merged_hooks(self.config).values())
            if ((kind in (tools.WRITE, tools.EXEC) or has_hooks)
                    and call.name not in ("git_checkpoint", "git_rollback")
                    and call.name != "browser_screenshot"
                    and not self.turn_checkpoint
                    and git_ops.repository(self.sandbox.root)):
                self.turn_checkpoint = git_ops.checkpoint(
                    self.sandbox.root, f"before session {self.session.id[:8]} mutation")
            before_hooks = (await hook_mod.run("before_tool", call.name, self.sandbox,
                                               self.config) if hooks_enabled else [])
            if before_hooks:
                yield Notice(f"ran {len(before_hooks)} before-tool hook(s)")
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
                    result = await tools.execute(
                        call.name, call.arguments, self.sandbox,
                        timeout=float(self.config.get("shell_timeout", 120) or 120),
                        max_bytes=int(self.config.get("max_output_bytes", 200_000)
                                      or 200_000),
                        on_output=chunks.append,
                        isolation=str(self.config.get("execution_isolation", "none")),
                        isolate_network=bool(self.config.get("isolate_network", False)))
            is_error = False
        except asyncio.CancelledError:
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
                yield Notice(f"ran {len(after_hooks)} after-tool hook(s)")
        except (ToolError, EireneError) as exc:
            result = f"{result}\nafter_tool hook failed: {exc.user_message()}"
            is_error = True

        seconds = time.monotonic() - started
        if chunks:
            yield ToolOutput(call.id, "".join(chunks))
        vision_image = None
        if call.name == "read_image" and not is_error:
            try:
                from .attachments import prepare_image
                vision_image = prepare_image(
                    self.sandbox, str(call.arguments.get("path") or ""))
            except EireneError as exc:
                result = f"{result}\nvision payload failed: {exc.user_message()}"
                is_error = True
        self.session.add_tool_result(call.id, call.name, result, is_error, seconds)
        if vision_image:
            self.session.add_user(
                f"Image content loaded from {call.arguments.get('path')}.", [vision_image])
        self.logger.info("tool.finished", extra={"session_id": self.session.id,
                                                 "tool": call.name,
                                                 "seconds": seconds,
                                                 "failed": is_error})
        yield ToolFinished(call.id, call.name, label, result, is_error, seconds)

    def _serialise_call(self, call: ToolCall) -> dict[str, Any]:
        """Keep enough presentation data to redraw tool activity on resume."""
        record: dict[str, Any] = {"id": call.id, "name": call.name,
                                  "arguments": call.arguments}
        label = tools.describe(call.name, call.arguments, self.sandbox)
        if label:
            record["label"] = label
        if call.name in CHANGE_TOOLS:
            preview = tools.preview(call.name, call.arguments, self.sandbox)
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
        if self.mode is Mode.AUTO:
            message = ("auto mode does not ask questions; decide the safest "
                       "reasonable answer yourself and continue")
            self.session.add_tool_result(call.id, call.name, message, False)
            yield ToolFinished(call.id, call.name, question, message, False, 0.0)
            return
        if not options or self.choose is None:
            message = ("no one is here to answer; decide yourself and say what "
                       "you assumed")
            self.session.add_tool_result(call.id, call.name, message, False)
            yield ToolFinished(call.id, call.name, question, message, False, 0.0)
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
    import os
    if os.name == "nt":
        return "cmd"
    return "sh"
