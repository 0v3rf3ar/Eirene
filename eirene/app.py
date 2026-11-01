"""The Textual application."""

from __future__ import annotations

import asyncio
import os
import re
import sys
import textwrap
import threading
import time
from datetime import datetime
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import events
from textual._compositor import CompositorUpdate
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches

from . import __version__, commands
from .core import agent as agent_mod
from .core import crash, notify, paths, questions
from .core import logging as runtime_logging
from .core import plans as plan_mod
from .core import recap as recap_mod
from .core import skills as skills_mod
from .core.attachments import (MAX_DROPPED_FILES, attachment_manifest, store_attachment,
                               store_attachment_bytes)
from .core.config import Config
from .core.errors import EireneError, ProviderError
from .core.modes import Mode, next_mode
from .core.session import Session, clean_title, name_from
from .core.usage import Usage as UsageTotals
from .providers import registry as providers
from .tools import registry as tool_registry
from .tools import processes
from .tools.sandbox import Sandbox
from .ui import art, guard, input_guard, links, markup
from .ui import theme as theme_mod
from .ui.shortcuts import COPY_KEYS, INERT_COPY_KEYS, SHORTCUTS
from .ui.terminal import copy_to_system, osc52, remote_session, write_terminal_title
from .ui.theme import THEMES
from .ui.format import display_path
from .ui.aside import AsidePanel
from .ui.chat import (AnswerBlock, ArtBlock, BackToBottom, ChangeBlock, CommandBlock,
                      DiffBlock, FLUSH_INTERVAL, NoticeBlock, PromptNavigator, RecapBlock,
                      ToolBlock, Transcript, UserBlock)
from .ui.complete import SlashMenu
from .ui.diff_panel import DiffPanel, DiffToggle
from .ui.composer import Composer, ModeLine, Prompt
from .ui.companion import Companion, prepare_renderer
from .ui.permission import PermissionBar
from .ui.picker import Picker
from .ui.processes import ProcessBar
from .ui.status import ContextIndicator, StatusLine, clock_label, elapsed_label
from .ui.compaction import CompactionProgress
from .ui.splash import StartupSplash
from .ui.tasks import TaskList
from .ui.copy_notice import CopyNotice

TAB_TICK = 0.25
IDLE_ESCAPE_WINDOW = 2.0


SHELL_TOOLS = ("run_command", "start_process", "poll_process", "Bash", "BashOutput", "KillShell")
PLAN_TOOLS = frozenset({"plan_update", "plan_set_status", "plan_clear"})
# Polling tools only refresh an earlier card; they never get one of their own.
HIDDEN_TOOLS = frozenset({"poll_process", "read_output"})


def _fit(value: str, width: int) -> str:
    """Crop or pad text to an exact terminal-cell width."""
    body = Text(str(value), no_wrap=True, overflow="ellipsis")
    body.truncate(max(width, 1), overflow="ellipsis", pad=True)
    return body.plain


UNNAMED_TITLE = "eirene"


class Eirene(App):
    """Terminal agent for coding and automation."""

    ENABLE_COMMAND_PALETTE = False
    TITLE = "eirene"

    CSS = """
    Screen {
        background: $background;
        layers: base overlay notification diff splash;
    }
    """

    BINDINGS = [
        Binding("ctrl+d", "leave", "exit", priority=True, show=False),
        Binding("escape", "interrupt", "stop", priority=True, show=False),
        Binding("shift+tab", "cycle_mode", "mode", priority=True, show=False),
        Binding(",".join(COPY_KEYS), "copy_selection", "copy", priority=True, show=False),
        Binding("ctrl+e", "jump_to_end", "jump to bottom", priority=True, show=False),
        Binding("pageup", "scroll_transcript(-1)", "scroll up", priority=True, show=False),
        Binding("pagedown", "scroll_transcript(1)", "scroll down", priority=True, show=False),
    ] + [Binding(key, "ignore", "", priority=True, show=False)
         for key in INERT_COPY_KEYS] + [Binding(key, action, hint, priority=True, show=False)
         for key, action, _, hint in SHORTCUTS]

    CONTAIN_ERRORS = True
    """Recover from unexpected handler errors instead of exiting; tests opt out."""
    EXIT_CONFIRM_SECONDS = 3.0
    """How long a second ctrl+d has to confirm exiting while work is running."""

    def __init__(self, sandbox: Path, resume: str = ""):
        super().__init__()
        guard.install()
        input_guard.install()
        self._error_budget = guard.ErrorBudget()
        # Containment starts once the widget tree exists; earlier failures are fatal.
        self._containing = False
        self._fatal: tuple[BaseException, Path | None] | None = None
        self._debug = bool(os.environ.get("EIRENE_DEBUG"))
        self._previous_hooks: tuple[Any, Any] | None = None
        paths.ensure_tree()
        self.sandbox = Sandbox(sandbox)
        self.config = Config.load()
        if os.environ.get("EIRENE_REDUCE_MOTION"):
            self.config.set("reduce_motion", True)
        art.set_accessible(bool(self.config.get("accessible_icons", False)))
        # Before the graphics probe, so its warnings reach the log, not the screen.
        self.runtime_logger = runtime_logging.configure(self.config)
        self._companion_renderer = prepare_renderer(self.config)
        self.session = Session.create(self.sandbox.root, resume or None)
        paths.use_session_temp(self.sandbox.root, self.session.id)
        self._resume_id = resume
        self.agent = agent_mod.Agent(self.session, self.config, self.sandbox)
        self.agent.approve = self._approve
        self.agent.choose = self._choose
        self.turn: asyncio.Task | None = None
        self.command: asyncio.Task | None = None
        self.asides: set[asyncio.Task] = set()
        self._aside_task: asyncio.Task | None = None
        self._text_future: asyncio.Future[str | None] | None = None
        self._new_session = not resume
        # The drawing chosen for this chat, and a smaller stand-in while the
        # window is too narrow for it.
        self._banner: str | None = None
        self._banner_fallback: str | None = None
        self._tip = art.tip()
        self._titled = bool(self.session.name)
        self._busy = False
        self._tab_tick = 0
        self._tab_timer = None
        self._flusher = None
        self._idle_escape_at = 0.0
        self._suggestion_generation = 0
        self._suggestion_task = None
        self._suggestion_status = "Waiting for a completed reply"
        self._last_suggestion_exchange = None
        self._recaps: dict[str, recap_mod.Tracker] = {}
        self._fast_state = ""
        self._fast_checked: tuple | None = None
        self._recap_task = None
        self.restart_requested = False
        self._mouse_captured = True
        self._clipboard_hinted = False
        self._exit_armed = float("-inf")

    # layout

    def _display(self, screen, renderable):
        # Textual's Windows driver does not probe synchronized output. Windows
        # Terminal supports it; older versions safely ignore the private mode.
        if (sys.platform == "win32" and os.environ.get("WT_SESSION")
                and self._driver is not None and not self._driver.is_inline):
            self._sync_available = True
        from .ui.sixel_portrait import PortraitUpdate, SixelPortrait
        if isinstance(renderable, CompositorUpdate):
            portraits = screen.query(SixelPortrait)
            if portraits:
                renderable = PortraitUpdate(renderable, portraits.first())
        super()._display(screen, renderable)

    def compose(self) -> ComposeResult:
        # Split off the right edge, so the chat and composer share the rest.
        yield DiffPanel(self.sandbox.root)
        yield Transcript()
        yield PromptNavigator()
        yield BackToBottom()
        yield AsidePanel()
        yield Composer(Picker(), PermissionBar(), SlashMenu(), StatusLine(),
                       TaskList(self.sandbox.root, self.session.id))
        yield Companion(self._companion_renderer)
        yield CopyNotice()
        yield DiffToggle()
        yield StartupSplash()

    @property
    def transcript(self) -> Transcript:
        return self.query_one(Transcript)

    @property
    def status(self) -> StatusLine:
        return self.query_one(StatusLine)

    @property
    def process_bar(self) -> ProcessBar:
        return self.query_one(ProcessBar)

    @property
    def aside(self) -> AsidePanel:
        return self.query_one(AsidePanel)

    @property
    def picker(self) -> Picker:
        return self.query_one(Picker)

    @property
    def permission(self) -> PermissionBar:
        return self.query_one(PermissionBar)

    @property
    def slash(self) -> SlashMenu:
        return self.query_one(SlashMenu)

    @property
    def prompt(self) -> Prompt:
        return self.query_one(Prompt)

    @property
    def mode_line(self) -> ModeLine:
        return self.query_one(ModeLine)

    @property
    def tasks(self) -> TaskList:
        return self.query_one(TaskList)

    @property
    def companion(self) -> Companion:
        return self.query_one(Companion)

    # lifecycle

    def on_mount(self) -> None:
        self._containing = True
        self._install_error_hooks()
        for theme in THEMES.values():
            self.register_theme(theme)
        selected = str(self.config.get("theme", "default"))
        self.theme = THEMES.get(selected, THEMES["default"]).name
        self.call_after_refresh(self._show_intro)
        self.agent.mode = Mode(self.config.mode)
        # Each optional step fails alone: a broken skill or plugin export must
        # not leave the prompt unfocused or the live transcript unflushed.
        from .core.plugin_install import export_installed_skills
        self._attempt("startup: remove seeded skills", skills_mod.remove_seeded_examples)
        self._attempt("startup: export plugin skills", export_installed_skills)
        self._attempt("startup: load skills", self.agent.reload_skills)
        self._attempt("startup: restore provider", self._restore_provider)
        self.refresh_mode_line()
        self._attempt("startup: load plan", self.refresh_plan)
        self._flusher = self.set_interval(FLUSH_INTERVAL, self._flush_live)
        self.name_the_tab()
        self.prompt.focus()
        self.call_after_refresh(self._start_mouse_mode)
        if self.config.get("check_updates", True) and not os.environ.get("EIRENE_NO_UPDATE_CHECK"):
            self.run_worker(self._check_updates(), group="update-check", exclusive=True)

    async def _check_updates(self) -> None:
        """Startup networking never delays mounting or interrupts provider setup."""
        from .core import updates
        try:
            release = await updates.check()
            if release:
                self.say(f"Eirene {release.version} is available (current: {__version__}). Run /update to install it.")
        except (updates.UpdateError, OSError, TimeoutError) as exc:
            self.runtime_logger.debug("update.check_failed", extra={"reason": str(exc)})

    # errors

    def contain_error(self, error: BaseException, where: str) -> bool:
        """Record an unexpected error; True when the app recovered and keeps running.

        Called by the dispatch guard, for failed background tasks, and as the
        last-chance handler. False means the caller must let the app exit.
        """
        contained = (self.CONTAIN_ERRORS and self._containing
                     and isinstance(error, Exception) and not guard.escalated(error)
                     and self._error_budget.spend())
        report = crash.record(error, where=where, fatal=not contained,
                              context={"session": self.session.id})
        if not contained:
            self._fatal = (error, report)
            guard.mark_escalated(error)
            return False
        try:
            self._tell_error(error, where, report)
        except Exception:  # noqa: BLE001 - already recorded; never fail while reporting
            pass
        return True

    def _tell_error(self, error: BaseException, where: str, report: Path | None) -> None:
        message = f"Something went wrong ({crash.summary(error)}). Eirene recovered; your session is intact."
        if self._debug:
            message += f" In {where}."
        if report is not None:
            message += f" Details: {display_path(report, 90)}"
        self.say(message, "warn")

    def _handle_exception(self, error: Exception) -> None:
        """Textual's last-chance handler: timers, workers, callbacks and rendering."""
        if not guard.escalated(error) and self.contain_error(error, "background"):
            return
        if self._fatal is None or self._fatal[0] is not error:
            self._fatal = (error, crash.record(error, where="unhandled", fatal=True))
        super()._handle_exception(error)

    def _fatal_error(self) -> None:
        """Exit after an unrecoverable error, without Textual's local-variable dump.

        Locals of the failing frames can hold API keys and configuration; they
        stay out of the terminal and its scrollback. The crash report has the rest.
        """
        from rich.segment import Segments
        from rich.traceback import Traceback

        error, report = self._fatal or (sys.exc_info()[1], None)
        if error is None:
            super()._fatal_error()
            return
        self.bell()
        traceback = Traceback.from_exception(type(error), error, error.__traceback__,
                                             show_locals=False, max_frames=20, width=None)
        notice = Text("\nEirene stopped after an unexpected error.", style="bold")
        if report is not None:
            notice.append(f"\nCrash report: {report}", style="")
        self._exit_renderables.append(Segments(self.console.render(traceback, self.console.options)))
        self._exit_renderables.append(Segments(self.console.render(notice, self.console.options)))
        self._close_messages_no_wait()

    @property
    def crash_report(self) -> Path | None:
        """The report for the error that ended this run, if one did."""
        return self._fatal[1] if self._fatal else None

    def _attempt(self, where: str, step: Callable[[], object]) -> None:
        """Run a step whose failure should be reported rather than end the app."""
        try:
            step()
        except Exception as error:  # noqa: BLE001
            if not self.contain_error(error, where):
                raise

    def spawn(self, coroutine: Coroutine[Any, Any, Any], *, name: str,
              background: bool = True) -> asyncio.Task:
        """Start a task whose unexpected failure is reported instead of silently lost.

        Background tasks are cancelled at shutdown; turns and commands are
        tracked by their own attributes instead.
        """
        task = asyncio.create_task(coroutine, name=f"eirene:{name}")
        if background:
            self.asides.add(task)
            task.add_done_callback(self.asides.discard)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is None:
            return
        if not self.contain_error(error, f"task {task.get_name()}"):
            if isinstance(error, Exception):
                self._handle_exception(error)
            else:
                self.exit(return_code=1)

    def _install_error_hooks(self) -> None:
        """Route asyncio and thread failures to the log rather than the screen."""
        loop = asyncio.get_running_loop()
        self._previous_hooks = (loop.get_exception_handler(), threading.excepthook)
        loop.set_exception_handler(self._loop_exception)
        threading.excepthook = self._thread_exception

    def _remove_error_hooks(self) -> None:
        if self._previous_hooks is None:
            return
        loop_handler, thread_hook = self._previous_hooks
        self._previous_hooks = None
        try:
            asyncio.get_running_loop().set_exception_handler(loop_handler)
        except RuntimeError:
            pass
        if threading.excepthook == self._thread_exception:
            threading.excepthook = thread_hook

    def _loop_exception(self, loop: asyncio.AbstractEventLoop, context: dict) -> None:
        """Library tasks that fail unobserved are logged, not shown: they are not ours to report."""
        error = context.get("exception")
        detail = str(context.get("message") or "")
        if isinstance(error, BaseException):
            crash.record(error, where=f"asyncio: {detail or 'unobserved task'}")
        else:
            self.runtime_logger.warning("asyncio.error", extra={"detail": detail[:500]})

    def _thread_exception(self, args: threading.ExceptHookArgs) -> None:
        if args.exc_type is SystemExit or args.exc_value is None:
            return
        name = args.thread.name if args.thread is not None else "unknown"
        crash.record(args.exc_value, where=f"thread {name}")

    def watch_theme(self, theme_name: str) -> None:
        """Re-colour every section that follows the theme's accents."""
        accent = theme_mod.accents(theme_name)
        markup.set_code_style(accent.code if accent else None)
        try:
            widgets = list(self.query("*"))
        except NoMatches:
            return
        for widget in widgets:
            restyle = getattr(widget, "restyle", None)
            if restyle is not None:
                restyle()

    def on_resize(self, event: events.Resize) -> None:
        """Keep the floating window inside a smaller terminal."""
        try:
            self.query_one(CopyNotice).place(event.size)
            self.query_one(DiffPanel).fit(event.size.width)
            if self.aside.open:
                self.aside._place(event.size)
                self.call_after_refresh(self.aside.refresh_body)
        except NoMatches:
            pass

    def tab_label(self) -> str:
        """The chat's own name alone once it has one, else just "eirene"."""
        return self.session.name or UNNAMED_TITLE

    def name_the_tab(self) -> None:
        """Put the chat name on the terminal tab."""
        label = self.tab_label()
        if self._busy:
            # The same spinner the chat's status line picked for this turn,
            # stepped at the title's own slower rate so no frames are skipped.
            frame = ("*" if self.config.get("reduce_motion", False)
                     else art.spinner_frame(self._tab_tick, self.status.spinner_style))
            label = f"{frame} {label}"
        write_terminal_title(getattr(self, "_driver", None), label)

    def refresh_plan(self) -> None:
        """Show only this session's unfinished plan."""
        plan = plan_mod.load(self.sandbox.root, self.session.id)
        if (plan.steps and
                all(step.status in {"completed", "blocked"} for step in plan.steps)):
            plan_mod.clear(self.sandbox.root, self.session.id)
        self.tasks.session_id = self.session.id
        self.tasks.refresh_plan()

    def mark_busy(self, busy: bool) -> None:
        """Spin the tab title while the agent works."""
        if busy == self._busy:
            return
        self._busy = busy
        if self.config.get("reduce_motion", False):
            self.name_the_tab()
            return
        if busy:
            self._tab_tick = 0
            self._tab_timer = self.set_interval(TAB_TICK, self._spin_tab)
        elif self._tab_timer is not None:
            self._tab_timer.stop()
            self._tab_timer = None
        self.name_the_tab()

    def _spin_tab(self) -> None:
        self._tab_tick += 1
        self.name_the_tab()

    async def _show_intro(self) -> None:
        """Banner, then anything the session already holds."""
        if self._resume_id:
            await self.switch_session(self._resume_id, initial=True)
        else:
            await self.push(ArtBlock(self._banner_text(), reflow=self._banner_text))

    async def replay_transcript(self) -> int:
        """Redraw a resumed conversation."""
        cards: dict[str, ToolBlock] = {}
        attachment_cards: dict[str, ToolBlock] = {}
        process_cards: dict[str, ToolBlock] = {}
        poll_processes: dict[str, str] = {}
        shown = 0
        history = self.session.transcript_messages or self.session.messages
        for message in history:
            role = message.get("role")
            body = str(message.get("content") or "")
            if role == "user":
                if not message.get("attachments"):
                    attachment_cards.clear()
                await self.push(UserBlock(body, file_tokens=[item["token"]
                    for item in message.get("files") or [] if item.get("token")]))
                shown += 1
            elif role == "assistant":
                if body.strip():
                    block = AnswerBlock()
                    block.feed(body)
                    await self.push(block)
                    block.flush()
                    shown += 1
                for call in message.get("tool_calls") or []:
                    if call.get("name") == "read_output":
                        continue
                    if call.get("name") == "poll_process":
                        poll_processes[str(call.get("id", ""))] = str(
                            (call.get("arguments") or {}).get("process_id", ""))
                        continue
                    attachment_id = str(call.get("attachment_id") or
                        ((call.get("arguments") or {}).get("attachment_id")
                         if call.get("name") == "read_attachment" else "") or "")
                    if attachment_id and attachment_id in attachment_cards:
                        cards[str(call.get("id", ""))] = attachment_cards[attachment_id]
                        continue
                    label = (call.get("label") or
                             tool_registry.describe(call.get("name", ""),
                                                    call.get("arguments") or {},
                                                    self.sandbox))
                    if call.get("preview"):
                        card = await self.push(ChangeBlock(
                            label, str(call.get("preview") or ""),
                            str(call.get("action") or "Update")))
                    else:
                        card = await self.push(self._tool_card(call.get("name", ""), label))
                    cards[str(call.get("id", ""))] = card
                    if attachment_id:
                        attachment_cards[attachment_id] = card
                    shown += 1
            elif role == "tool":
                call_id = str(message.get("tool_call_id", ""))
                card = cards.get(call_id)
                process_id = poll_processes.get(call_id)
                if process_id:
                    # Polls are hidden, but their terminal results belong to the
                    # original command, including host-generated completions.
                    if not body.startswith(f"{process_id}: exited "):
                        continue
                    card = process_cards.get(process_id)
                if card is not None:
                    pending = re.match(r"Still running as managed process ([\w-]+)", body)
                    if pending:
                        process_cards[pending[1]] = card
                    card.artifact_id = str(message.get("artifact_id") or "")
                    failed = bool(message.get("is_error"))
                    if process_id:
                        failed = failed or not body.startswith(f"{process_id}: exited 0; succeeded")
                    card.finish(body, failed,
                                card.seconds + float(message.get("seconds") or 0.0))
                    card.flush()
        self.prompt.recall_from([m.get("content", "") for m in history
                                 if m.get("role") == "user"])
        if shown:
            await self.push(NoticeBlock(
                f"resumed {shown} earlier messages - the model has them in context"))
        return shown

    def _banner_text(self, available_width: int = 0) -> str:
        """Responsive startup art with compact session details below it."""
        width = available_width or self.size.width or 80
        room = max(width, 1)
        art_room = max(width - art.BANNER_MARGIN, 1)
        full_size = {text for text, _ in art.SIZED}
        if self._banner is None:
            self._banner = art.banner(width)
        elif self._banner not in full_size and art.SIZED[0][1] <= art_room:
            # Started too narrow for real art; now there is room for some.
            self._banner = art.banner(width)
        if art.art_width(self._banner) <= art_room:
            # Wide enough again: bring back the same drawing as before.
            self._banner_fallback = None
            shown = self._banner
        else:
            fallback = self._banner_fallback
            if fallback is None or art.art_width(fallback) > art_room:
                fallback = self._banner_fallback = art.banner(width)
            shown = fallback
        lines = [shown, f"v{__version__}"[:room], ""]
        lines.extend(self._intro_panel(room))
        return "\n".join(lines)

    def _intro_panel(self, width: int) -> list[str]:
        """Project details beside one stable, randomly chosen tip."""
        if width < 24:
            rule = "─" * width
            path = display_path(self.sandbox.root, max(width - 2, 1))
            return [rule, f"{art.icon('dir')} {path}"[:width], rule]

        left = min(max(width * 2 // 5, 18), 42)
        right = width - left - 3
        top = f"{'─' * left}─┬─{'─' * right}"
        bottom = f"{'─' * left}─┴─{'─' * right}"
        left_rows = [
            f"{art.icon('dir')} {display_path(self.sandbox.root, max(left - 2, 1))}",
            f"{art.icon('link')} session {self.session.id[:8]}",
            f"{art.icon('info')} /help {art.icon('dot')} shift+tab {art.icon('dot')} ctrl+d",
        ]
        tip_rows = textwrap.wrap(f"Tip: {self._tip}", width=max(right, 1))[:3]
        tip_rows += [""] * (3 - len(tip_rows))
        rows = [f"{_fit(left_rows[index], left)} │ {_fit(tip_rows[index], right)}"
                for index in range(3)]
        return [top, *rows, bottom]

    def _restore_provider(self) -> None:
        key = self.config.provider
        if not key:
            self.call_after_refresh(self.say,
                                    "no provider yet - run /connect to add an API key")
            return
        try:
            key = providers.resolve_alias(key)
            model = (self.config.provider_config(key).get("model")
                     or self.config.model or providers.default_model(key))
            self.agent.use(providers.build(key, self.config), key, model)
        except EireneError as exc:
            self.call_after_refresh(self.say, exc.user_message(), "warn")

    def _flush_live(self) -> None:
        try:
            self.transcript.flush_live()
        except NoMatches:
            self._stop_flusher()

    # output helpers

    async def push(self, block, live: bool = False):
        return await self.transcript.push(block, live)

    async def show_compaction(self, stage: str = "preparing") -> CompactionProgress:
        progress = CompactionProgress()
        await self.query_one(Composer).mount(progress, before=self.query_one(ContextIndicator))
        progress.set_stage(stage)
        return progress

    def say(self, text: str, kind: str = "info", *, markdown: bool = False) -> None:
        """Queue a one-line notice."""
        self.call_later(self.push, NoticeBlock(text, kind, markdown=markdown))

    def refresh_mode_line(self) -> None:
        detail = ""
        if self.agent.provider_key:
            detail = f"{providers.display_name(self.agent.provider_key, compact=True)}({self.agent.model})"
            fast = self.agent.fast_state()
            if fast == "on":
                detail += " · fast"
            elif fast == "cooling":
                detail += " · fast (cooling down)"
        self.mode_line.show(self.agent.mode, detail)
        self._learn_fast_support()

    def _learn_fast_support(self) -> None:
        """Load the catalog that says whether this model has a fast tier.

        Codex and ChatGPT only know once their model list is read; /fast is
        listed as soon as it is.
        """
        provider, model = self.agent.provider, self.agent.model
        check = getattr(provider, "check_fast", None)
        key = (id(provider), model)
        if check is None or not model or key == self._fast_checked:
            return
        self._fast_checked = key

        async def learn() -> None:
            try:
                supported = await check(model)
            except Exception:  # noqa: BLE001 - /fast just stays unlisted
                self.runtime_logger.debug("fast.check_failed", exc_info=True)
                return
            if supported and self.agent.provider is provider and self.agent.model == model:
                self.refresh_mode_line()

        self.spawn(learn(), name="fast mode support")

    # input

    def on_prompt_draft(self, message: Prompt.Draft) -> None:
        """Keep the slash menu in step with the draft."""
        self.companion.wake()
        if message.text:
            self.clear_prompt_suggestion()
        # Bold the command name once it is completely written.
        available = commands.commands(self) if message.text.startswith("/") else []
        name = message.text[1:].split(maxsplit=1)[0].lower() if message.text[1:2].strip() else ""
        known = name in {"plugin", *commands.REGISTRY, *(c.name for c in available)}
        self.prompt.mark_command(len(name) + 1 if name and known else 0)
        if not message.suggest:
            self.slash.close()
            self.prompt.menu_open = False
            return
        self.prompt.menu_open = self.slash.update_for(message.text, available)

    def on_prompt_navigate(self, message: Prompt.Navigate) -> None:
        self.slash.move(message.delta)

    def on_prompt_accept(self, message: Prompt.Accept) -> None:
        """Enter runs the highlighted command; tab just completes it."""
        name = self.slash.choice
        self.slash.close()
        self.prompt.menu_open = False
        if not name:
            return
        command = commands.lookup(name, self)
        if message.run and command is not None and not command.wants_args:
            self.prompt.clear_draft()
            self.prompt.remember(f"/{name}")
            self._start_command(f"/{name}")
            return
        self.prompt.value = f"/{name} "

    def on_key(self, event: events.Key) -> None:
        """Any printable key types into the input."""
        self.companion.wake()
        if event.key != "escape":
            self._idle_escape_at = 0.0
        if self.picker.waiting or self.permission.waiting:
            return
        if self.prompt.has_focus or not event.is_printable or not event.character:
            return
        event.stop()
        event.prevent_default()
        self.prompt.focus()
        self.prompt.insert(event.character)

    async def on_paste(self, event: events.Paste) -> None:
        """Terminal drops can arrive while the transcript has focus."""
        if self.picker.waiting or self.permission.waiting:
            return
        self.prompt.focus()
        await self.prompt._on_paste(event)

    async def on_prompt_files_dropped(self, message: Prompt.FilesDropped) -> None:
        for path in message.paths:
            if not self._attach(lambda limit: store_attachment(path, limit)):
                break
        self.prompt.focus()

    async def on_prompt_image_pasted(self, message: Prompt.ImagePasted) -> None:
        image = message.image
        self._attach(lambda limit: store_attachment_bytes(image.filename, image.data, limit))
        self.prompt.focus()

    def _attach(self, store: Callable[[int], dict]) -> bool:
        """Store one attachment and put its token in the prompt; False once the limit is reached."""
        if len([token for token in self.prompt._files if token in self.prompt.text]) >= MAX_DROPPED_FILES:
            self.say(f"attach up to {MAX_DROPPED_FILES} files per message", "warn")
            return False
        try:
            self.prompt.attach_file(store(int(self.config.get("max_attachment_bytes", 20_000_000))))
        except EireneError as exc:
            self.say(str(exc), "warn")
        return True

    async def on_prompt_sent(self, message: Prompt.Sent) -> None:
        self._idle_escape_at = 0.0
        self.clear_prompt_suggestion()
        text = message.text
        self.slash.close()
        self.prompt.menu_open = False
        if self._text_future and not self._text_future.done():
            self._text_future.set_result(text)
            return
        if text.startswith("/"):
            self._start_command(text)
            return
        if message.files and not self.agent.ready:
            self.say("no provider selected; run /connect", "warn")
            self.prompt.value = text
            self.prompt._files = {item["token"]: item for item in message.files}
            self.prompt._line_cache.clear()
            self.prompt.refresh()
            return
        sent_text = attachment_manifest(text, message.files)
        if self.turn and not self.turn.done():
            self.agent.steer(sent_text, files=message.files)
            await self.push(UserBlock(text, file_tokens=[item["token"] for item in message.files]))
            self.say("queued for the next safe execution boundary")
            return
        old_plan = plan_mod.load(self.sandbox.root, self.session.id)
        if old_plan.steps and all(step.status in {"completed", "blocked"}
                                  for step in old_plan.steps):
            plan_mod.clear(self.sandbox.root, self.session.id)
            self.refresh_plan()
        if not self.session.name:
            self.session.name = name_from(text)
            self.name_the_tab()
        await self.push(UserBlock(text, file_tokens=[item["token"] for item in message.files]))
        self.turn = self.spawn(self._run_turn(sent_text, files=message.files),
                               name="turn", background=False)

    def _start_command(self, text: str) -> None:
        """Run a slash command in its own task."""
        if text.strip().lower() == "/snow":
            self.transcript._snowfall.toggle()
            return
        if self.command and not self.command.done():
            self.say("finish the current command first, or press esc", "warn")
            return
        self.command = self.spawn(self._run_command(text), name="command", background=False)

    async def _run_command(self, text: str) -> None:
        """Run a slash command off the message pump."""
        try:
            await commands.dispatch(self, text)
        except asyncio.CancelledError:
            await self.push(NoticeBlock("cancelled", "warn"))
            raise
        finally:
            try:
                self._close_prompts()
                self.prompt.focus()
            except NoMatches:
                pass

    def _close_prompts(self) -> None:
        """Dismiss any open picker or approval."""
        self.slash.close()
        self.prompt.menu_open = False
        self.picker.cancel()
        self.permission.cancel()
        if self._text_future and not self._text_future.done():
            self._text_future.set_result(None)

    async def ask_text(self, label: str, secret: bool = False) -> str | None:
        """Read one line through the prompt."""
        prompt = self.prompt
        previous = prompt.placeholder
        prompt.secret = secret
        prompt.placeholder = label
        prompt.value = ""
        prompt.focus()
        self._text_future = asyncio.get_running_loop().create_future()
        try:
            return await self._text_future
        except asyncio.CancelledError:
            return None
        finally:
            self._text_future = None
            prompt.secret = False
            prompt.placeholder = previous
            prompt.value = ""

    async def ask_choice(self, title: str, options: list[tuple], *,
                         on_highlight=None, selected: str = "",
                         right_hint: bool = False,
                         footer: str = "") -> str | None:
        """Pick one option from a list, opening on the one already in use."""
        try:
            self.picker.right_hint = right_hint
            return await self.picker.choose(title, options,
                                            on_highlight=on_highlight,
                                            selected=selected, footer=footer)
        finally:
            self.prompt.focus()

    async def ask_session_tree(self, rows, *, allow_switch=True):
        from .ui.session_tree import SessionTreeScreen
        screen = SessionTreeScreen(rows, self.session.id, allow_switch)
        future = asyncio.get_running_loop().create_future()
        def resolved(value):
            if not future.done():
                future.set_result(value)
        await self.push_screen(screen, resolved)
        try:
            return await future
        finally:
            if self.screen is screen:
                self.pop_screen()
            self.prompt.focus()

    async def _choose(self, question: str, options: list) -> str | None:
        """The model asked something; offer the answers."""
        rows = [(str(option), str(option), "") for option in options]
        rows.append((tool_registry.CHAT_OPTION, "chat about this",
                     "type an answer instead"))
        companion = self.companion
        companion.begin_question()
        try:
            return await self.picker.choose(question, rows)
        finally:
            companion.end_question()
            self.prompt.focus()

    async def _approve(self, name: str, label: str, preview: str,
                       reason: str) -> str:
        """Agent permission callback."""
        native_change = name.startswith("native_")
        if native_change:
            name = name.removeprefix("native_")
        if native_change and preview:
            if not any(card.diff_text == preview for card in self.transcript.query(ChangeBlock)):
                await self.push(ChangeBlock(label, preview, self._change_action(label)))
        repeated_name = (label == name or (name.startswith("mcp__") and
            label.replace("__", "_").casefold() == name.replace("__", "_").casefold()))
        title = name if not label or repeated_name else f"{name} {label}"
        if name == "run_command":
            title = f"run {label}"
        elif name == "request_full_access":
            title = "allow full host access for this response"
        if preview and name not in ("run_command",) + agent_mod.CHANGE_TOOLS:
            if not native_change:
                await self.push(DiffBlock(title, preview))
        companion = self.companion
        companion.begin_question()
        try:
            return await self.permission.ask(
                title, reason, edits=name in agent_mod.CHANGE_TOOLS, tool=name)
        finally:
            companion.end_question()
            self.prompt.focus()

    # the turn

    async def _run_turn(self, text: str, *, record_text: str | None = None,
                        attachments: list[dict] | None = None,
                        files: list[dict] | None = None) -> None:
        self.clear_prompt_suggestion()
        if self._recap_task is not None and not self._recap_task.done():
            # Don't compete with the new turn for the provider (local models).
            self._recap_task.cancel()
        self.status.start(art.session_spinner(self.session.id))
        self.companion.start_turn()
        self.mark_busy(True)
        answer: AnswerBlock | None = None
        reply_text = ""
        turn_completed = False
        cards: dict[str, ToolBlock] = {}
        attachment_cards: dict[str, ToolBlock] = {}
        compaction: CompactionProgress | None = None
        try:
            options = {"attachments": attachments} if attachments else {}
            if files:
                options["files"] = files
            async for event in self.agent.run(text, record_text=record_text, **options):
                if isinstance(event, (agent_mod.ToolStarted, agent_mod.ToolPreview,
                                      agent_mod.ToolFinished)) and event.name in HIDDEN_TOOLS:
                    continue
                if isinstance(event, agent_mod.Answer):
                    if event.text:
                        self.status.mark_activity()
                    reply_text += event.text
                    if answer is None:
                        answer = await self.push(AnswerBlock(), live=True)
                    answer.feed(event.text)
                elif isinstance(event, agent_mod.Thought):
                    self.status.set_phase("reasoning")
                elif isinstance(event, agent_mod.Phase):
                    self.status.set_phase(event.name)
                elif isinstance(event, agent_mod.Tokens):
                    self.status.set_tokens(event.input_tokens, event.output_tokens)
                elif isinstance(event, agent_mod.ContextCompaction):
                    self.status.set_phase("compacting context")
                    if event.stage == "complete":
                        if compaction is not None:
                            await compaction.remove()
                            compaction = None
                    else:
                        if compaction is None:
                            compaction = await self.show_compaction(event.stage)
                        compaction.set_stage(event.stage)
                elif isinstance(event, agent_mod.PlanChanged):
                    if event.steps:
                        objective = self.session.name or "Complete the current request"
                        plan_mod.update(self.sandbox.root, objective, event.steps,
                                        event.explanation, self.session.id)
                    else:
                        plan_mod.clear(self.sandbox.root, self.session.id)
                    self.refresh_plan()
                elif isinstance(event, agent_mod.ToolPreview):
                    self.clear_prompt_suggestion()
                    answer = None
                    cards[event.id] = await self.push(
                        ChangeBlock(event.label, event.diff,
                                    self._change_action(event.label)), live=True)
                elif isinstance(event, agent_mod.ToolStarted):
                    self.status.start_tool(event.id, event.kind)
                    self.companion.refresh_companion()
                    self.clear_prompt_suggestion()
                    answer = None
                    if event.attachment_id and event.attachment_id in attachment_cards:
                        card = attachment_cards[event.attachment_id]
                        cards[event.id] = card
                        card.finished = False
                        card.is_error = False
                        card.output = ""
                        card.result = ""
                        card.flush()
                    if event.name not in PLAN_TOOLS and event.id not in cards:
                        block = self._tool_card(event.name, event.label)
                        cards[event.id] = await self.push(block, live=True)
                        if event.attachment_id:
                            attachment_cards[event.attachment_id] = block
                elif isinstance(event, agent_mod.ToolOutput):
                    if event.chunk:
                        self.status.mark_activity()
                    card = cards.get(event.id)
                    if card:
                        card.feed(event.chunk)
                        if event.artifact_id:
                            card.artifact_id = event.artifact_id
                elif isinstance(event, agent_mod.ToolFinished):
                    self.status.finish_tool(event.id)
                    if event.reused:
                        continue
                    if event.name in PLAN_TOOLS:
                        self.refresh_plan()
                        continue
                    card = cards.get(event.id)
                    if card is None:
                        card = await self.push(self._tool_card(event.name, event.label))
                    card.finish(event.result, event.is_error, card.seconds + event.seconds)
                    card.artifact_id = event.artifact_id
                    card.flush()
                    self.query_one(DiffPanel).reload()
                elif isinstance(event, agent_mod.Notice):
                    if event.transient:
                        if event.phase in {"reconnecting", "waiting for response"}:
                            self.status.set_connection_wait()
                        else:
                            self.status.set_phase(event.phase)
                        continue
                    answer = None
                    await self.push(NoticeBlock(event.text))
                elif isinstance(event, agent_mod.Failed):
                    answer = None
                    await self.push(NoticeBlock(self._friendly_failure(event.text)))
                elif isinstance(event, agent_mod.TurnDone):
                    self.transcript.settle()
                    self.status.stop(self._turn_note(event),
                                     "done" if event.status == "completed" else "dot")
                    self.companion.finish_turn(
                        event.status == "completed" and questions.wants_an_answer(reply_text))
                    self._announce_done(event, answer)
                    self._name_the_session(record_text or text, answer)
                    self._offer_choices(answer)
                    if event.status == "completed":
                        turn_completed = True
                        self._last_suggestion_exchange = (self.session.id, record_text or text, reply_text)
                        self._offer_prompt_suggestion(record_text or text, reply_text)
                        self._offer_recap()
        except asyncio.CancelledError:
            try:
                self.transcript.settle()
                self.status.stop("stopped")
                self.companion.finish_turn(False)
                await self.push(NoticeBlock("stopped", "warn"))
            except NoMatches:
                pass
            raise
        finally:
            if compaction is not None:
                await compaction.remove()
            if not turn_completed:
                self.clear_prompt_suggestion()
            self.mark_busy(False)
            try:
                if self.status.active:
                    self.status.stop()
                self.transcript.settle()
                self._note_fast_fallback()
                self.prompt.focus()
            except NoMatches:
                pass

    def _note_fast_fallback(self) -> None:
        """Say once when fast limits pushed this session back to standard speed."""
        state = self.agent.fast_state()
        if state == "cooling" and self._fast_state != "cooling":
            self.say("fast mode limit reached · continuing at standard speed; "
                     "fast resumes on its own after a short cooldown", "warn")
        self._fast_state = state
        self.refresh_mode_line()

    def _name_the_session(self, request: str, answer) -> None:
        """Let the model name a fresh session."""
        if self._titled or not self.session.saved or not self.agent.ready:
            return
        self._titled = True
        reply = getattr(answer, "buffer", "") or ""
        self.spawn(self._ask_for_a_title(request, reply), name="session title")

    async def _ask_for_a_title(self, request: str, reply: str) -> None:
        try:
            raw = await self.agent.title(request, reply)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a missing title is cosmetic
            self.runtime_logger.warning("session.title_failed", exc_info=True)
            return
        title = clean_title(raw)
        if not title or not self.session.saved:
            return
        self.session.rename(title)
        self.name_the_tab()

    def _offer_recap(self) -> None:
        """Measure once the finished turn is laid out, then maybe recap."""
        session, turn = self.session, self.turn
        self.call_after_refresh(self._maybe_recap, session, turn)

    def _transcript_height(self) -> tuple[int, int]:
        """Rendered transcript height and the visible screen height, in rows."""
        return self.transcript.virtual_size.height, self.transcript.size.height

    def _maybe_recap(self, session, turn) -> None:
        """Show a short recap once the chat has grown by a couple of screens."""
        if (not self.config.get("recap", True) or not self.agent.ready
                or session is not self.session or self.turn is not turn):
            return
        if self._recap_task is not None and not self._recap_task.done():
            return
        try:
            height, screen = self._transcript_height()
        except NoMatches:
            return
        tracker = self._recaps.setdefault(session.id, recap_mod.Tracker())
        if not tracker.due(height, screen):
            return

        async def generate():
            try:
                text = await asyncio.wait_for(self.agent.recap(), 120)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a recap is optional
                self.runtime_logger.warning("recap.failed", exc_info=True)
                text = ""
            # Never interleave with a newer turn's output or another session;
            # a later completed turn retries since the mark did not move.
            if session is not self.session or self.turn is not turn:
                return
            # A failed or unusable reply waits for more growth instead of
            # costing a request after every turn.
            tracker.shown(height)
            if text and self.config.get("recap", True):
                await self.push(RecapBlock(text))

        self._recap_task = self.spawn(generate(), name="session recap")

    def clear_prompt_suggestion(self) -> None:
        self._suggestion_generation += 1
        if self._suggestion_task is not None and not self._suggestion_task.done():
            self._suggestion_task.cancel()
        self._suggestion_task = None
        try:
            self.prompt.prompt_suggestion = ""
        except NoMatches:
            pass  # The input is already gone while the app shuts down.

    def _set_suggestion_status(self, text: str) -> None:
        self._suggestion_status = text

    def set_prompt_suggestions(self, enabled: bool) -> None:
        self.config.set("prompt_suggest", enabled)
        self.config.save()
        self.clear_prompt_suggestion()
        self._set_suggestion_status("Waiting for a completed reply" if enabled else "Disabled")
        if not enabled or (self.turn and not self.turn.done()):
            return
        exchange = self._last_suggestion_exchange
        if exchange and exchange[0] == self.session.id:
            self._offer_prompt_suggestion(exchange[1], exchange[2])
            return
        # Enabling after a reply (including a resumed session) should work now,
        # not require the user to send another prompt first.
        request = reply = ""
        for message in self.session.messages:
            if message.get("role") == "user":
                request, reply = str(message.get("content") or ""), ""
            elif message.get("role") == "assistant" and message.get("content"):
                reply = str(message["content"])
        if request and reply:
            self._offer_prompt_suggestion(request, reply)

    def on_prompt_suggestion_accepted(self, message: Prompt.SuggestionAccepted) -> None:
        if self.picker.waiting or self.permission.waiting or self.prompt.text:
            return
        suggestion = self.prompt.prompt_suggestion
        self.clear_prompt_suggestion()
        if suggestion:
            self._set_suggestion_status("Copied to input")
            self.prompt.value = suggestion
            self.prompt.focus()

    def _offer_prompt_suggestion(self, request: str, answer) -> None:
        if not self.config.get("prompt_suggest", False):
            return
        if not self.agent.ready:
            self._set_suggestion_status("Connect a provider first (/connect)")
            return
        reply = answer if isinstance(answer, str) else getattr(answer, "buffer", "") or ""
        if not reply.strip():
            self._set_suggestion_status("Waiting for a completed reply")
            return
        self.clear_prompt_suggestion()
        if questions.options_from(reply):
            self._set_suggestion_status("Skipped · the reply already offers choices")
            return
        generation = self._suggestion_generation
        session = self.session
        self._set_suggestion_status("Generating…")
        async def generate():
            try:
                suggestion = await asyncio.wait_for(self.agent.suggest_prompt(request, reply), 120)
                if (generation != self._suggestion_generation
                        or session is not self.session or self.prompt.text
                        or not self.config.get("prompt_suggest", False)):
                    return
                if not suggestion:
                    self._set_suggestion_status("No suggestion returned; switch off/on to retry")
                    return
                # Don't discard a valid suggestion just because a choice UI is
                # momentarily open. New input/turns cancel this task instead.
                while self.picker.waiting or self.permission.waiting:
                    await asyncio.sleep(0.1)
                self.prompt.prompt_suggestion = suggestion
                self._set_suggestion_status("Ready · Tab or → to accept")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - suggestions are optional
                self.runtime_logger.warning("suggestion.failed", exc_info=True)
                detail = "Request timed out" if isinstance(exc, asyncio.TimeoutError) else "Provider request failed"
                self._set_suggestion_status(detail + "; switch off/on to retry")
        self._suggestion_task = self.spawn(generate(), name="prompt suggestion")

    def _offer_choices(self, answer) -> None:
        """A question in prose still becomes a choice."""
        if self.agent.mode is Mode.AUTO:
            return
        body = getattr(answer, "buffer", "") or ""
        if not body.strip() or not questions.wants_an_answer(body):
            return
        self.spawn(self._choices_for(body), name="answer choices")

    async def _choices_for(self, body: str) -> None:
        options = questions.options_from(body)
        if not options and self.agent.ready:
            try:
                options = await self.agent.options_for(body)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - choices are a convenience
                self.runtime_logger.warning("choices.failed", exc_info=True)
                options = []
        if len(options) < 2:
            return
        if self.turn and not self.turn.done():
            return
        self.clear_prompt_suggestion()
        chosen = await self._choose(questions.question_from(body), options)
        if not chosen or chosen == tool_registry.CHAT_OPTION:
            return
        await self.push(UserBlock(chosen))
        self.turn = self.spawn(self._run_turn(chosen), name="turn", background=False)

    @staticmethod
    def _friendly_failure(detail: str) -> str:
        lowered = detail.lower()
        if "context" in lowered or "budget" in lowered:
            return "Your progress is saved. This model needs a shorter request or a larger context setting to continue."
        if any(word in lowered for word in ("connection", "unreachable", "timed out", "offline")):
            return "I couldn’t reach the model. Your progress is saved; reconnect and continue when it’s available."
        # Configuration and permission failures still need their actionable reason.
        return detail

    def _tool_card(self, name: str, label: str) -> ToolBlock:
        """The transcript card for one tool call."""
        if name in SHELL_TOOLS:
            return CommandBlock(name, label)
        # Profile-driven providers summarise their own searches in the answer.
        return ToolBlock(name, label, hide_output=name == "web_search" and
                         getattr(self.agent.provider, "profile", None) is not None)

    def _change_action(self, label: str) -> str:
        """Create or Update, from what is on disk."""
        try:
            return "Update" if self.sandbox.resolve(label).exists() else "Create"
        except EireneError:
            return "Update"

    def _announce_done(self, event: agent_mod.TurnDone, answer) -> None:
        """Tell the desktop the turn is over."""
        if not self.config.get("notifications", False):
            return
        body = " ".join(getattr(answer, "buffer", "").split())[:140] if answer else ""
        if not body and event.seconds < 1 and not event.usage.total:
            return
        title = self.session.name or self.sandbox.root.name or "eirene"
        notify.send(title, body or f"done in {event.seconds:.0f}s")

    def _turn_note(self, event: agent_mod.TurnDone, now: datetime | None = None) -> str:
        finished = clock_label(now or datetime.now())
        if event.status != "completed":
            return f"{event.status} · {elapsed_label(event.seconds)} · {finished}"
        if event.seconds < 1 and not event.usage.total:
            return ""
        parts = [f"{art.done_verb()} for {elapsed_label(event.seconds)}"]
        if event.usage.output_tokens:
            parts.append(f"{art.icon('tokens')} {event.usage.output_tokens} tokens")
        parts.append(finished)
        return " · ".join(parts)

    # actions

    def action_manage_processes(self) -> None:
        self.process_bar.action_manage()

    def action_interrupt(self) -> None:
        """Close an output viewer before interrupting work underneath it."""
        from .ui.output import OutputScreen
        from .ui.session_tree import SessionTreeScreen
        if isinstance(self.screen, (OutputScreen, SessionTreeScreen)):
            self.screen.dismiss()
            return
        if self.aside.open:
            self.aside.close()
            self.prompt.focus()
            return
        if self.slash.open:
            self.slash.close()
            self.prompt.menu_open = False
            return
        if self.picker.waiting or self.permission.waiting:
            self._close_prompts()
            self.prompt.focus()
            return
        if self._text_future and not self._text_future.done():
            self._text_future.set_result(None)
            self.prompt.focus()
            return
        if self.turn and not self.turn.done():
            self.turn.cancel()
            return
        if self.command and not self.command.done():
            self.command.cancel()
            return
        if self.prompt.value:
            self.prompt.clear_draft()
            return
        now = time.monotonic()
        if now - self._idle_escape_at <= IDLE_ESCAPE_WINDOW:
            self._idle_escape_at = 0.0
            self.run_worker(self._confirm_exit(), group="exit-confirmation",
                            exclusive=True)
            return
        self._idle_escape_at = now
        self.say("press esc again to choose whether to exit", "warn")

    async def _confirm_exit(self) -> None:
        """Ask before leaving after a deliberate idle double-Escape."""
        answer = await self.ask_choice("exit eirene?", [
            ("yes", "yes", "exit now"),
            ("no", "no", "stay in this session"),
        ])
        if answer == "yes":
            self.action_leave()
        else:
            self.prompt.focus()

    def action_ignore(self) -> None:
        """Swallow a key that would otherwise reach a built-in binding."""

    def action_copy_selection(self) -> None:
        """Copy the editor selection or selected transcript text."""
        text = self.prompt.selected_text if self.prompt.has_focus else ""
        if not text:
            try:
                text = self.screen.get_selected_text() or ""
            except NoMatches:
                text = ""
        if not text:
            if not self._mouse_captured:
                return  # The terminal owns selection and copying in this mode.
            self.say("nothing selected - drag over the text first", "warn")
            return
        self.copy_to_clipboard(text)
        tool = copy_to_system(text)
        self.query_one(CopyNotice).show_count(len(text))
        self.screen.clear_selection()
        if remote_session():
            self._clipboard_hint()
        elif not tool:
            self.say("copied, but no clipboard tool was found - "
                     "install wl-clipboard or xclip", "warn")

    def copy_to_clipboard(self, text: str) -> None:
        """Have the terminal showing Eirene set its clipboard, across SSH and tmux."""
        self._clipboard = text
        if self._driver is not None:
            self._driver.write(osc52(text))
            self._driver.flush()

    def _clipboard_hint(self) -> None:
        """Over SSH only the user's terminal can reach their clipboard; say how once."""
        if self._clipboard_hinted:
            return
        self._clipboard_hinted = True
        self.say("copied through your terminal (OSC 52) to the computer you are typing on. "
                 "If it does not paste, allow clipboard access in your terminal's settings"
                 + (", and add `set -g set-clipboard on` to ~/.tmux.conf" if os.environ.get("TMUX") else "")
                 + ".")

    def open_url(self, url: str, *, new_tab: bool = True) -> None:
        """Open a transcript link on the user's desktop, never blocking or crashing the UI.

        Over SSH a browser here would open on the server: show the whole link to the
        user's own terminal instead, and offer it to their clipboard too. Links that
        are not web or mail addresses are copied, never launched (see ui.links).
        """
        if remote_session():
            self.copy_to_clipboard(url)
            self.show_outside(url)
            return
        if not links.launchable(url):
            self.copy_to_clipboard(url)
            self.say("only web and mail links open from Eirene; copied this one to the clipboard "
                     "instead", "warn")
            return
        self.run_worker(self._launch_link(url), group="open-link")

    async def _launch_link(self, url: str) -> None:
        try:
            await asyncio.wait_for(asyncio.to_thread(links.open_external, url),
                                   links.LAUNCH_SECONDS + 5)
        except (links.LinkError, OSError, TimeoutError) as exc:
            self.runtime_logger.info("link.open_failed", extra={"reason": str(exc)[:300]})
            self.copy_to_clipboard(url)
            self.say(f"couldn't open the link ({exc}); copied it to the clipboard instead", "warn")

    def on_mouse_down(self, event: events.MouseDown) -> None:
        companion = self.companion
        if event.button == 1 and companion.poke_at(event.screen_x, event.screen_y):
            event.stop()
            event.prevent_default()
            return
        companion.wake()

    def on_click(self, event: events.Click) -> None:
        """Double click selects the word under the pointer, not the whole block."""
        if event.chain != 2:
            return
        from textual.content import Content
        from textual.geometry import Offset
        from textual.selection import Selection
        from textual.widgets import Input, TextArea
        widget, offset = self.screen.get_widget_and_offset_at(event.screen_x, event.screen_y)
        if widget is None or offset is None or isinstance(widget, (Input, TextArea)):
            return
        visual = widget._render()
        if not isinstance(visual, (Text, Content)):
            return
        lines = str(visual).splitlines()
        line = lines[offset.y] if offset.y < len(lines) else ""
        word = next((m for m in re.finditer(r"\w+", line) if m.start() <= offset.x < m.end()), None)
        if word is None:
            self.screen.clear_selection()
            return
        self.screen.selections = {widget: Selection(Offset(word.start(), offset.y),
                                                    Offset(word.end(), offset.y))}

    def clear_session(self) -> None:
        """Forget this session and its log."""
        self.clear_prompt_suggestion()
        if self.turn and not self.turn.done():
            self.say("still working - press esc first", "warn")
            return
        self.session.clear()
        self.agent.always.clear()
        self._titled = False
        self._recaps.pop(self.session.id, None)
        self.name_the_tab()
        self.agent.usage = UsageTotals()
        plan_mod.clear(self.sandbox.root, self.session.id)
        self.refresh_plan()
        reset_provider = getattr(self.agent.provider, "reset_thread", None)
        if reset_provider:
            reset_provider()
        self.transcript.reset()
        self.call_later(self.push, ArtBlock(
            self._banner_text(), reflow=self._banner_text))

    async def switch_session(self, session_id: str, *, initial: bool = False) -> None:
        """Replace the active session and redraw its saved conversation."""
        self.clear_prompt_suggestion()
        if session_id == self.session.id and not initial:
            self.say("already in that session")
            return
        if self.turn and not self.turn.done():
            self.say("still working - press esc first", "warn")
            return
        previous = self.session
        splash = self.query_one(StartupSplash)
        splash.start()
        await asyncio.sleep(0)
        try:
            with ThreadPoolExecutor(max_workers=1) as loader:
                resumed = await asyncio.get_running_loop().run_in_executor(
                    loader, Session.resume, session_id)
        except EireneError as exc:
            splash.finish()
            self.say(exc.user_message(), "warn")
            return
        except Exception:
            splash.finish()
            raise
        try:
            previous.close()
            self.session = resumed
            self.agent.session = resumed
            paths.use_session_temp(self.sandbox.root, resumed.id)
            self.agent.always.clear()
            self.agent.usage = UsageTotals()
            reset_provider = getattr(self.agent.provider, "reset_thread", None)
            if reset_provider:
                reset_provider()
            self._titled = bool(resumed.name)
            self.refresh_plan()
            self.transcript.reset()
            await self.push(ArtBlock(self._banner_text(), reflow=self._banner_text))
            await self.replay_transcript()
            self.name_the_tab()
        finally:
            splash.finish()

    def _modal_open(self) -> bool:
        """A popup screen, choice, approval or text request is waiting on the user."""
        return bool(len(self.screen_stack) > 1 or self.picker.waiting or self.permission.waiting
                    or self._text_future and not self._text_future.done())

    def _shortcut_command(self, command: str) -> None:
        # Leave active choices and secret/text-entry requests undisturbed.
        if self._modal_open():
            return
        self.slash.close()
        self.prompt.menu_open = False
        self._start_command(command)

    def action_help_menu(self) -> None:
        self._shortcut_command("/help")

    def action_keybindings(self) -> None:
        self._shortcut_command("/keybindings")

    def action_pick_model(self) -> None:
        self._shortcut_command("/model")

    def action_pick_session(self) -> None:
        self._shortcut_command("/sessions")

    def action_pick_theme(self) -> None:
        self._shortcut_command("/theme")

    def action_toggle_suggestions(self) -> None:
        if self._modal_open():
            return
        self.set_prompt_suggestions(not self.config.get("prompt_suggest", False))
        state = "ON" if self.config.get("prompt_suggest", False) else "OFF"
        self.say(f"prompt suggestions {state}")

    def _start_mouse_mode(self) -> None:
        """Over SSH default to the terminal's own selection, copying and link clicks."""
        setting = self.config.get("mouse", "auto")
        self._apply_mouse(setting == "eirene" or (setting == "auto" and not remote_session()))

    def _apply_mouse(self, captured: bool) -> None:
        """Turn mouse reporting on (Eirene handles clicks) or off (the terminal does)."""
        self._mouse_captured = captured
        driver = self._driver
        switch = getattr(driver, "_enable_mouse_support" if captured else "_disable_mouse_support", None)
        if switch is None:
            return
        switch()
        if not captured:
            # Without reporting, terminals turn the wheel into arrow keys on the
            # alternate screen, which would page through prompt history.
            driver.write("\x1b[?1007l")
            driver.flush()

    def action_toggle_mouse(self) -> None:
        self._apply_mouse(not self._mouse_captured)
        self.say("Mouse: Eirene - click blocks and links, drag then Ctrl+Shift+C to copy."
                 if self._mouse_captured else
                 "Mouse: your terminal's own selection - drag to select, copy with your terminal's "
                 "shortcut, Ctrl+click links. PageUp/PageDown scroll. F4 switches back.")

    def check_action(self, action: str, parameters) -> bool | None:
        if action == "scroll_transcript":
            # Only while typing in the main screen; popups keep their own paging.
            return len(self.screen_stack) == 1 and self.focused is self.prompt
        return super().check_action(action, parameters)

    def action_scroll_transcript(self, direction: int) -> None:
        try:
            transcript = self.transcript
        except NoMatches:
            return
        transcript.scroll_to(y=transcript.scroll_y + direction * max(1, transcript.size.height - 2), animate=False)

    def show_outside(self, text: str) -> None:
        """Print text on the normal terminal screen, where a long link wraps as one link
        that the terminal can select or open whole; inside the full-screen view each
        row is separate, so only its first row is recognized."""
        driver = self._driver
        if driver is None or not getattr(driver, "can_suspend", False):
            self.copy_to_clipboard(text)
            return
        with self.suspend():
            sys.stdout.write("\n" + text + "\n\nSelect it or Ctrl+click it, then press Enter to return to Eirene. ")
            sys.stdout.flush()
            try:
                sys.stdin.readline()
            except (OSError, ValueError):
                pass
        # Resuming re-enables mouse reporting.
        self._apply_mouse(self._mouse_captured)

    def action_jump_to_end(self) -> None:
        try:
            self.transcript.go_to_bottom()
        except NoMatches:
            pass

    def action_leave(self, *, restart: bool = False) -> None:
        """Exit, asking for a second press while work would be cut off."""
        busy = self._running_work()
        armed = time.monotonic() - self._exit_armed
        if busy and armed > self.EXIT_CONFIRM_SECONDS:
            self._exit_armed = time.monotonic()
            verb = "is" if busy in (["the agent"], ["1 command"]) else "are"
            again = "type /restart" if restart else "press ctrl+d or type /exit"
            self.say(f"{' and '.join(busy)} {verb} still running; {again} again within "
                     f"{self.EXIT_CONFIRM_SECONDS:.0f}s to stop it and "
                     f"{'restart' if restart else 'exit'}", "warn")
            return
        self.restart_requested = restart
        self.shutdown()
        self.exit()

    def action_quit(self) -> None:
        """Textual's ctrl+q goes through the same confirmation as ctrl+d."""
        self.action_leave()

    def _running_work(self) -> list[str]:
        from .tools import activity, shell
        busy = []
        if self.turn and not self.turn.done():
            busy.append("the agent")
        commands = len(processes.running()) + len(shell.active()) + len(activity.provider_commands())
        if commands:
            busy.append(f"{commands} command{'s' if commands != 1 else ''}")
        return busy

    def action_cycle_mode(self) -> None:
        self.agent.mode = next_mode(self.agent.mode)
        self.config.mode = self.agent.mode.value
        self._save_config()
        self.refresh_mode_line()

    # side channel

    def start_aside(self, question: str) -> None:
        """Ask in a popup, without touching the session."""
        if self._aside_task is not None and not self._aside_task.done():
            self._aside_task.cancel()
        panel = self.aside
        panel.ask(question)
        self._aside_task = self.spawn(self._aside(question), name="btw")

    async def _aside(self, question: str) -> None:
        panel = self.aside
        try:
            async for chunk in self.agent.aside(question):
                if asyncio.current_task() is not self._aside_task:
                    return
                panel.feed(chunk)
                panel.refresh_body()
        except asyncio.CancelledError:
            if asyncio.current_task() is self._aside_task:
                panel.finish("stopped", failed=True)
            raise
        except (ProviderError, EireneError) as exc:
            if asyncio.current_task() is self._aside_task:
                panel.finish(exc.user_message(), failed=True)
            return
        except Exception as exc:  # noqa: BLE001
            report = crash.record(exc, where="btw")
            if asyncio.current_task() is self._aside_task:
                detail = f" (details: {display_path(report, 90)})" if report else ""
                panel.finish(f"btw failed: {crash.summary(exc)}{detail}", failed=True)
            return
        if asyncio.current_task() is self._aside_task:
            panel.finish(panel.answer.strip() or "(no answer)")

    # teardown

    def _save_config(self) -> None:
        try:
            self.config.save()
        except EireneError as exc:
            self.say(exc.user_message(), "warn")

    def _stop_flusher(self) -> None:
        if self._tab_timer is not None:
            self._tab_timer.stop()
            self._tab_timer = None
        if self._flusher is not None:
            self._flusher.stop()
            self._flusher = None

    def shutdown(self) -> None:
        self._stop_flusher()
        for task in list(self.asides):
            task.cancel()
        if self.turn and not self.turn.done():
            self.turn.cancel()
        self._save_config()
        self.session.close()

    async def on_unmount(self) -> None:
        # Teardown steps are independent: a failure in one must not skip the rest,
        # or managed processes and provider subprocesses outlive the app.
        self._attempt("shutdown: save session", self.shutdown)
        for where, step in (("shutdown: stop processes", processes.stop_all),
                            ("shutdown: close agent", self.agent.close)):
            try:
                await step()
            except Exception as error:  # noqa: BLE001
                crash.record(error, where=where)
        self._remove_error_hooks()


def invocation() -> str:
    """How this program was started."""
    argument = sys.argv[0] if sys.argv else ""
    name = Path(argument).name if argument else ""
    if getattr(sys, "frozen", False):
        return argument or "eirene"
    if not name or name in ("__main__.py", "-c"):
        return f"{Path(sys.executable).name} -m eirene"
    return argument


def restart_argv(sandbox: Path, session_id: str = "") -> list[str]:
    """Start this same installation again; after /update that is the new binary."""
    program = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "eirene"]
    return program + ["-C", str(sandbox)] + (["--resume", session_id] if session_id else [])


def relaunch(argv: list[str]) -> int:
    """Replace this process with a fresh Eirene (Windows: run it, then pass on its code)."""
    # A one-file build must unpack itself afresh instead of reusing this
    # process's extraction, or the restart would still run the old code.
    os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    if os.name == "nt":
        # execv on Windows starts a child and exits, handing the console back
        # to the shell while the new Eirene is still drawing on it.
        import subprocess
        return subprocess.call(argv)
    os.execv(argv[0], argv)
    return 0  # not reached


def run(sandbox: Path, resume: str = "") -> int:
    """Start the TUI."""
    from .ui.trust import confirm_workspace_trust

    sandbox = sandbox.expanduser().resolve()
    if not confirm_workspace_trust(sandbox):
        return 0
    app = Eirene(sandbox, resume)
    app.run()
    if getattr(app, "restart_requested", False):
        sys.stdout.write("restarting eirene…\n")
        sys.stdout.flush()
        return relaunch(restart_argv(sandbox, app.session.id if app.session.saved else ""))
    if app.session.saved:
        sys.stdout.write(
            f"{art.BANNERS[0]}\n{invocation()} --resume {app.session.id}\n")
    return app.return_code or 0
