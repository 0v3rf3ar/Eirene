"""The Textual application."""

from __future__ import annotations

import asyncio
import os
import sys
import textwrap
import time
from pathlib import Path

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches

from . import __version__, commands
from .core import agent as agent_mod
from .core import notify, paths, questions
from .core import skills as skills_mod
from .core import plans as plan_mod
from .core.config import Config
from .core.compact import compact as compact_history
from .core import logging as runtime_logging
from .core.errors import EireneError, ProviderError
from .core.modes import Mode, next_mode
from .core.session import Session, clean_title, name_from
from .core.usage import Usage as UsageTotals, human_count
from .providers import registry as providers
from .tools import registry as tool_registry
from .tools import processes
from .tools.sandbox import Sandbox
from .ui import art, markup
from .ui import theme as theme_mod
from .ui.terminal import copy_to_system, write_terminal_title
from .ui.theme import THEMES
from .ui.format import display_path
from .ui.aside import AsidePanel
from .ui.chat import (AnswerBlock, ArtBlock, BackToBottom, ChangeBlock, CommandBlock,
                      DiffBlock, NoticeBlock, PromptNavigator, ThinkingBlock,
                      ToolBlock, Transcript, UserBlock)
from .ui.complete import SlashMenu
from .ui.composer import Composer, ModeLine, Prompt
from .ui.permission import PermissionBar
from .ui.picker import Picker
from .ui.processes import ProcessBar
from .ui.status import StatusLine
from .ui.tasks import TaskList

TAB_TICK = 0.25
IDLE_ESCAPE_WINDOW = 2.0


SHELL_TOOLS = ("run_command", "Bash", "BashOutput", "KillShell")


def _fit(value: str, width: int) -> str:
    """Crop or pad text to an exact terminal-cell width."""
    body = Text(str(value), no_wrap=True, overflow="ellipsis")
    body.truncate(max(width, 1), overflow="ellipsis", pad=True)
    return body.plain


class Eirene(App):
    """Terminal agent for coding and automation."""

    ENABLE_COMMAND_PALETTE = False
    TITLE = "eirene"

    CSS = """
    Screen {
        background: $background;
        layers: base overlay;
    }
    """

    BINDINGS = [
        Binding("ctrl+d", "leave", "exit", priority=True, show=False),
        Binding("escape", "interrupt", "stop", priority=True, show=False),
        Binding("shift+tab", "cycle_mode", "mode", priority=True, show=False),
        Binding("ctrl+shift+c", "copy_selection", "copy", priority=True, show=False),
        Binding("ctrl+c", "copy_selection(True)", "copy", priority=True, show=False),
        Binding("ctrl+e", "jump_to_end", "jump to bottom", priority=True, show=False),
    ]

    def __init__(self, sandbox: Path, resume: str = ""):
        super().__init__()
        paths.ensure_tree()
        self.sandbox = Sandbox(sandbox)
        self.config = Config.load()
        if os.environ.get("EIRENE_REDUCE_MOTION"):
            self.config.set("reduce_motion", True)
        art.set_accessible(bool(self.config.get("accessible_icons", False)))
        self.runtime_logger = runtime_logging.configure(self.config)
        self.session = (Session.resume(resume) if resume
                        else Session.create(self.sandbox.root))
        self.agent = agent_mod.Agent(self.session, self.config, self.sandbox)
        self.agent.approve = self._approve
        self.agent.choose = self._choose
        self.turn: asyncio.Task | None = None
        self.command: asyncio.Task | None = None
        self.asides: set[asyncio.Task] = set()
        self._text_future: asyncio.Future[str | None] | None = None
        self._banner: str | None = None
        self._tip = art.tip()
        self._titled = bool(self.session.name)
        self._busy = False
        self._warned_context = False
        self._tab_tick = 0
        self._tab_timer = None
        self._flusher = None
        self._idle_escape_at = 0.0

    # layout

    def compose(self) -> ComposeResult:
        yield ProcessBar()
        yield Transcript()
        yield PromptNavigator()
        yield BackToBottom()
        yield AsidePanel()
        yield Composer(Picker(), PermissionBar(), SlashMenu(), StatusLine(),
                       TaskList(self.sandbox.root))

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

    # lifecycle

    def on_mount(self) -> None:
        for theme in THEMES.values():
            self.register_theme(theme)
        selected = str(self.config.get("theme", "default"))
        self.theme = THEMES.get(selected, THEMES["default"]).name
        self.call_after_refresh(self._show_intro)
        self.agent.mode = Mode(self.config.mode)
        skills_mod.seed()
        self.agent.reload_skills()
        self._restore_provider()
        self.refresh_mode_line()
        self.tasks.refresh_plan()
        self._flusher = self.set_interval(1 / 20, self._flush_live)
        self.name_the_tab()
        self.prompt.focus()

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
            if self.aside.open:
                self.aside._place(event.size)
                self.call_after_refresh(self.aside.refresh_body)
        except NoMatches:
            pass

    def name_the_tab(self) -> None:
        """Put the chat name on the terminal tab."""
        label = self.session.name or self.sandbox.root.name or "eirene"
        if self._busy:
            mark = art.spinner_frame(self._tab_tick)
            write_terminal_title(getattr(self, "_driver", None),
                                 f"{mark} eirene - {label}")
            return
        write_terminal_title(getattr(self, "_driver", None), f"eirene - {label}")

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
        await self.push(ArtBlock(self._banner_text(), reflow=self._banner_text))
        await self.replay_transcript()

    async def replay_transcript(self) -> int:
        """Redraw a resumed conversation."""
        cards: dict[str, ToolBlock] = {}
        shown = 0
        history = self.session.transcript_messages or self.session.messages
        for message in history:
            role = message.get("role")
            body = str(message.get("content") or "")
            if role == "user":
                await self.push(UserBlock(body))
                shown += 1
            elif role == "assistant":
                if body.strip():
                    block = AnswerBlock()
                    block.feed(body)
                    await self.push(block)
                    block.flush()
                    shown += 1
                for call in message.get("tool_calls") or []:
                    label = (call.get("label") or
                             tool_registry.describe(call.get("name", ""),
                                                    call.get("arguments") or {},
                                                    self.sandbox))
                    if call.get("preview"):
                        card = await self.push(ChangeBlock(
                            label, str(call.get("preview") or ""),
                            str(call.get("action") or "Update")))
                    elif call.get("name") == "run_command":
                        card = await self.push(CommandBlock(call.get("name", ""), label))
                    else:
                        card = await self.push(ToolBlock(call.get("name", ""), label))
                    cards[str(call.get("id", ""))] = card
                    shown += 1
            elif role == "tool":
                card = cards.get(str(message.get("tool_call_id", "")))
                if card is not None:
                    card.finish(body, bool(message.get("is_error")),
                                float(message.get("seconds") or 0.0))
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
        if self._banner is None or art.art_width(self._banner) > art_room:
            self._banner = art.banner(width)
        lines = [self._banner, f"v{__version__}"[:room], ""]
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

    def say(self, text: str, kind: str = "info") -> None:
        """Queue a one-line notice."""
        self.call_later(self.push, NoticeBlock(text, kind))

    def refresh_mode_line(self) -> None:
        detail = ""
        if self.agent.provider_key:
            detail = f"{self.agent.provider_key} {self.agent.model}"
            profile = getattr(self.agent.provider, "profile", None)
            if profile is not None:
                detail += f" · {profile.tier}"
        self.mode_line.show(self.agent.mode, detail)

    # input

    def on_prompt_draft(self, message: Prompt.Draft) -> None:
        """Keep the slash menu in step with the draft."""
        if not message.suggest:
            self.slash.close()
            self.prompt.menu_open = False
            return
        self.prompt.menu_open = self.slash.update_for(message.text,
                                                      commands.commands(self))

    def on_prompt_navigate(self, message: Prompt.Navigate) -> None:
        self.slash.move(message.delta)

    def on_prompt_accept(self, message: Prompt.Accept) -> None:
        """Enter runs the highlighted command; tab just completes it."""
        name = self.slash.choice
        self.slash.close()
        self.prompt.menu_open = False
        if not name:
            return
        command = commands.lookup(name)
        if message.run and command is not None and not command.wants_args:
            self.prompt.clear_draft()
            self.prompt.remember(f"/{name}")
            self._start_command(f"/{name}")
            return
        self.prompt.value = f"/{name} "

    def on_key(self, event: events.Key) -> None:
        """Any printable key types into the input."""
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

    async def on_prompt_sent(self, message: Prompt.Sent) -> None:
        self._idle_escape_at = 0.0
        text = message.text
        self.slash.close()
        self.prompt.menu_open = False
        if self._text_future and not self._text_future.done():
            self._text_future.set_result(text)
            return
        if text.startswith("/"):
            self._start_command(text)
            return
        if self.turn and not self.turn.done():
            self.say("still working - use /btw to ask something on the side", "warn")
            return
        old_plan = plan_mod.load(self.sandbox.root)
        if old_plan.steps and all(step.status in {"completed", "blocked"}
                                  for step in old_plan.steps):
            plan_mod.clear(self.sandbox.root)
            self.tasks.refresh_plan()
        if not self.session.name:
            self.session.name = name_from(text)
            self.name_the_tab()
        await self.push(UserBlock(text))
        self.turn = asyncio.create_task(self._run_turn(text))

    def _start_command(self, text: str) -> None:
        """Run a slash command in its own task."""
        if self.command and not self.command.done():
            self.say("finish the current command first, or press esc", "warn")
            return
        self.command = asyncio.create_task(self._run_command(text))

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
        prompt.placeholder = label
        prompt.secret = secret
        prompt.value = ""
        prompt.focus()
        self._text_future = asyncio.get_running_loop().create_future()
        try:
            return await self._text_future
        except asyncio.CancelledError:
            return None
        finally:
            self._text_future = None
            prompt.placeholder = previous
            prompt.secret = False
            prompt.value = ""

    async def ask_choice(self, title: str, options: list[tuple], *,
                         on_highlight=None, selected: str = "") -> str | None:
        """Pick one option from a list, opening on the one already in use."""
        try:
            return await self.picker.choose(title, options,
                                            on_highlight=on_highlight,
                                            selected=selected)
        finally:
            self.prompt.focus()

    async def _choose(self, question: str, options: list) -> str | None:
        """The model asked something; offer the answers."""
        rows = [(str(option), str(option), "") for option in options]
        rows.append((tool_registry.CHAT_OPTION, "chat about this",
                     "type an answer instead"))
        try:
            return await self.picker.choose(question, rows)
        finally:
            self.prompt.focus()

    async def _approve(self, name: str, label: str, preview: str,
                       reason: str) -> str:
        """Agent permission callback."""
        native_change = name.startswith("native_")
        if native_change and preview:
            name = name.removeprefix("native_")
            await self.push(DiffBlock(f"{name} {label}", preview))
        if preview and name not in ("run_command",) + agent_mod.CHANGE_TOOLS:
            if not native_change:
                await self.push(DiffBlock(f"{name} {label}", preview))
        title = f"run {label}" if name == "run_command" else f"{name} {label}"
        try:
            return await self.permission.ask(title, reason)
        finally:
            self.prompt.focus()

    # the turn

    async def _run_turn(self, text: str, *, record_text: str | None = None) -> None:
        self.status.start()
        self.mark_busy(True)
        answer: AnswerBlock | None = None
        thought: ThinkingBlock | None = None
        cards: dict[str, ToolBlock] = {}
        try:
            async for event in self.agent.run(text, record_text=record_text):
                if isinstance(event, agent_mod.Answer):
                    if answer is None:
                        answer = await self.push(AnswerBlock(), live=True)
                    answer.feed(event.text)
                elif isinstance(event, agent_mod.Thought):
                    if thought is None:
                        thought = await self.push(ThinkingBlock(), live=True)
                    thought.feed(event.text)
                elif isinstance(event, agent_mod.Phase):
                    self.status.set_phase(event.name)
                elif isinstance(event, agent_mod.Tokens):
                    self.status.set_tokens(event.input_tokens, event.output_tokens)
                elif isinstance(event, agent_mod.PlanChanged):
                    if event.steps:
                        objective = self.session.name or "Complete the current request"
                        plan_mod.update(self.sandbox.root, objective, event.steps,
                                        event.explanation)
                    else:
                        plan_mod.clear(self.sandbox.root)
                    self.tasks.refresh_plan()
                elif isinstance(event, agent_mod.ToolPreview):
                    answer = thought = None
                    cards[event.id] = await self.push(
                        ChangeBlock(event.label, event.diff,
                                    self._change_action(event.label)), live=True)
                elif isinstance(event, agent_mod.ToolStarted):
                    answer = thought = None
                    if (event.name not in {"plan_update", "plan_set_status", "plan_clear"}
                            and event.id not in cards):
                        block = (CommandBlock(event.name, event.label)
                                 if event.name in SHELL_TOOLS
                                 else ToolBlock(event.name, event.label))
                        cards[event.id] = await self.push(block, live=True)
                elif isinstance(event, agent_mod.ToolOutput):
                    card = cards.get(event.id)
                    if card:
                        card.feed(event.chunk)
                elif isinstance(event, agent_mod.ToolFinished):
                    if event.name in {"plan_update", "plan_set_status", "plan_clear"}:
                        self.tasks.refresh_plan()
                        continue
                    card = cards.get(event.id)
                    if card is None:
                        block = (CommandBlock(event.name, event.label)
                                 if event.name in SHELL_TOOLS
                                 else ToolBlock(event.name, event.label))
                        card = await self.push(block)
                    card.finish(event.result, event.is_error, event.seconds)
                    card.flush()
                elif isinstance(event, agent_mod.Notice):
                    answer = thought = None
                    await self.push(NoticeBlock(event.text, "warn"))
                elif isinstance(event, agent_mod.Failed):
                    answer = thought = None
                    await self.push(NoticeBlock(event.text, "fail"))
                elif isinstance(event, agent_mod.TurnDone):
                    self.transcript.settle()
                    self.status.stop(self._turn_note(event))
                    self._announce_done(event, answer)
                    self._name_the_session(record_text or text, answer)
                    await self._manage_context()
                    self._offer_choices(answer)
        except asyncio.CancelledError:
            try:
                self.transcript.settle()
                self.status.stop("stopped")
                await self.push(NoticeBlock("stopped", "warn"))
            except NoMatches:
                pass
            raise
        finally:
            self.mark_busy(False)
            try:
                if self.status.active:
                    self.status.stop()
                self.transcript.settle()
                self.prompt.focus()
            except NoMatches:
                pass

    def _name_the_session(self, request: str, answer) -> None:
        """Let the model name a fresh session."""
        if self._titled or not self.session.saved or not self.agent.ready:
            return
        self._titled = True
        reply = getattr(answer, "buffer", "") or ""
        task = asyncio.create_task(self._ask_for_a_title(request, reply))
        self.asides.add(task)
        task.add_done_callback(self.asides.discard)

    async def _ask_for_a_title(self, request: str, reply: str) -> None:
        try:
            raw = await self.agent.title(request, reply)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            return
        title = clean_title(raw)
        if not title or not self.session.saved:
            return
        self.session.rename(title)
        self.name_the_tab()

    def _offer_choices(self, answer) -> None:
        """A question in prose still becomes a choice."""
        if self.agent.mode is Mode.AUTO:
            return
        body = getattr(answer, "buffer", "") or ""
        if not body.strip() or not questions.wants_an_answer(body):
            return
        task = asyncio.create_task(self._choices_for(body))
        self.asides.add(task)
        task.add_done_callback(self.asides.discard)

    async def _choices_for(self, body: str) -> None:
        options = questions.options_from(body)
        if not options and self.agent.ready:
            try:
                options = await self.agent.options_for(body)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                options = []
        if len(options) < 2:
            return
        if self.turn and not self.turn.done():
            return
        chosen = await self._choose(questions.question_from(body), options)
        if not chosen or chosen == tool_registry.CHAT_OPTION:
            return
        await self.push(UserBlock(chosen))
        self.turn = asyncio.create_task(self._run_turn(chosen))

    async def _manage_context(self) -> None:
        """Automatically compact or suggest it once history gets big."""
        if self._warned_context or not self.agent.context_is_heavy():
            return
        self._warned_context = True
        size = human_count(self.agent.context_size())
        if self.config.get("auto_compact", False) and self.agent.ready:
            try:
                before, after, _ = await compact_history(
                    self.session, self.agent.provider, self.agent.model)
                self.say(f"context auto-compacted {human_count(before)} → "
                         f"{human_count(after)} tokens")
                self._warned_context = False
                return
            except EireneError as exc:
                self.say(f"automatic compaction failed: {exc.user_message()}", "warn")
        self.say(f"this chat is about {size} tokens - /compact will shrink it "
                 "and keep the agent sharp (optional)", "warn")

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

    def _turn_note(self, event: agent_mod.TurnDone) -> str:
        if event.seconds < 1 and not event.usage.total:
            return ""
        parts = [f"{event.seconds:.0f}s"]
        if event.usage.output_tokens:
            parts.append(f"{art.icon('tokens')} {event.usage.output_tokens} tokens")
        if event.thinking_seconds >= 1:
            parts.append(f"thought for {event.thinking_seconds:.0f}s")
        return " · ".join(parts)

    # actions

    def action_interrupt(self) -> None:
        """Esc, in priority order."""
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

    def action_copy_selection(self, quiet: bool = False) -> None:
        """Copy whatever the mouse selected."""
        text = ""
        try:
            text = self.screen.get_selected_text() or ""
        except NoMatches:
            text = ""
        if not text:
            if not quiet:
                self.say("nothing selected - drag over the text first", "warn")
            return
        self.copy_to_clipboard(text)
        tool = copy_to_system(text)
        self.screen.clear_selection()
        if not tool:
            self.say("copied, but no clipboard tool was found - "
                     "install wl-clipboard or xclip", "warn")

    def on_mouse_down(self, event: events.MouseDown) -> None:
        """Right click copies the selection."""
        if event.button != 3:
            return
        event.stop()
        event.prevent_default()
        self.action_copy_selection()

    def clear_session(self) -> None:
        """Forget this session and its log."""
        if self.turn and not self.turn.done():
            self.say("still working - press esc first", "warn")
            return
        self.session.clear()
        self._titled = False
        self._warned_context = False
        self.agent.usage = UsageTotals()
        reset_provider = getattr(self.agent.provider, "reset_thread", None)
        if reset_provider:
            reset_provider()
        self.transcript.reset()
        self.call_later(self.push, ArtBlock(
            self._banner_text(), reflow=self._banner_text))

    async def switch_session(self, session_id: str) -> None:
        """Replace the active session and redraw its saved conversation."""
        if session_id == self.session.id:
            self.say("already in that session")
            return
        if self.turn and not self.turn.done():
            self.say("still working - press esc first", "warn")
            return
        previous = self.session
        try:
            resumed = Session.resume(session_id)
        except EireneError as exc:
            self.say(exc.user_message(), "warn")
            return
        previous.close()
        self.session = resumed
        self.agent.session = resumed
        self.agent.usage = UsageTotals()
        reset_provider = getattr(self.agent.provider, "reset_thread", None)
        if reset_provider:
            reset_provider()
        self._titled = bool(resumed.name)
        self._warned_context = False
        self.transcript.reset()
        await self.push(ArtBlock(self._banner_text(), reflow=self._banner_text))
        await self.replay_transcript()
        self.name_the_tab()

    def action_jump_to_end(self) -> None:
        try:
            self.transcript.go_to_bottom()
        except NoMatches:
            pass

    def action_leave(self) -> None:
        self.shutdown()
        self.exit()

    def action_cycle_mode(self) -> None:
        self.agent.mode = next_mode(self.agent.mode)
        self.config.mode = self.agent.mode.value
        self._save_config()
        self.refresh_mode_line()

    # side channel

    def start_aside(self, question: str) -> None:
        """Ask in a popup, without touching the session."""
        panel = self.aside
        panel.ask(question)
        task = asyncio.create_task(self._aside(question))
        self.asides.add(task)
        task.add_done_callback(self.asides.discard)

    async def _aside(self, question: str) -> None:
        panel = self.aside
        try:
            async for chunk in self.agent.aside(question):
                panel.feed(chunk)
                panel.refresh_body()
        except asyncio.CancelledError:
            panel.finish("stopped", failed=True)
            raise
        except (ProviderError, EireneError) as exc:
            panel.finish(exc.user_message(), failed=True)
            return
        except Exception as exc:  # noqa: BLE001
            panel.finish(f"btw failed: {exc}", failed=True)
            return
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
        self.shutdown()
        await processes.stop_all()
        await self.agent.close()


def invocation() -> str:
    """How this program was started."""
    argument = sys.argv[0] if sys.argv else ""
    name = Path(argument).name if argument else ""
    if getattr(sys, "frozen", False):
        return argument or "eirene"
    if not name or name in ("__main__.py", "-c"):
        return f"{Path(sys.executable).name} -m eirene"
    return argument


def run(sandbox: Path, resume: str = "") -> int:
    """Start the TUI."""
    app = Eirene(sandbox, resume)
    app.run()
    if app.session.saved:
        sys.stdout.write(
            f"to continue this session use: {invocation()} --resume {app.session.id}\n")
    return 0
