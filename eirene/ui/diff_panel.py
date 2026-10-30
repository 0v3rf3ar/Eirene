"""The /diff side panel: uncommitted Git changes beside the chat."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from rich.text import Text
from textual import events
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from ..core.subprocesses import external_environment
from . import diff, palette

REFRESH_SECONDS = 2.0
GIT_TIMEOUT = 10.0
MAX_PATCH = 2_000_000
CLOSE = "×"
ASK = "[ ask ]"
TO_DIFF = "diff→"
TO_CHAT = "← chat"
# Below this many columns the panel and the chat take turns at full width.
NARROW_WIDTH = 100


@dataclass
class FileDiff:
    """One changed path."""

    path: str
    change: diff.Change | None = None
    untracked: bool = False
    binary: bool = False

    @property
    def added(self) -> int:
        return self.change.added if self.change else 0

    @property
    def removed(self) -> int:
        return self.change.removed if self.change else 0


@dataclass
class Snapshot:
    """Everything the panel shows, plus the raw text it came from."""

    files: list[FileDiff] = field(default_factory=list)
    error: str = ""
    key: str = ""

    @property
    def added(self) -> int:
        return sum(item.added for item in self.files)

    @property
    def removed(self) -> int:
        return sum(item.removed for item in self.files)


async def _git(root: Path, *args: str, stdin: bytes | None = None) -> tuple[int, str]:
    git = shutil.which("git")
    if git is None:
        return 127, "git is not installed"
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    process = await asyncio.create_subprocess_exec(
        git, "-C", str(root), "-c", "core.quotepath=off", *args,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env={**external_environment(), "GIT_OPTIONAL_LOCKS": "0"}, **kwargs)
    try:
        out, err = await asyncio.wait_for(process.communicate(stdin), GIT_TIMEOUT)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return 124, "git timed out"
    text = (out if process.returncode == 0 else err).decode("utf-8", "replace")
    return process.returncode or 0, text


def _path_of(chunk: str) -> tuple[str, bool]:
    """The new-side path of one `diff --git` section, and whether it is binary."""
    path = ""
    binary = False
    for line in chunk.splitlines()[1:]:
        if line.startswith("@@"):
            break
        if line.startswith("rename to "):
            path = line[len("rename to "):]
        elif line.startswith("+++ ") and line[4:] != "/dev/null":
            path = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("--- ") and not path and line[4:] != "/dev/null":
            path = line[6:] if line.startswith("--- a/") else line[4:]
        elif line.startswith("Binary files "):
            binary = True
    if not path:
        head = chunk.splitlines()[0]
        path = head.rsplit(" b/", 1)[-1] if " b/" in head else head[len("diff --git "):]
    return path, binary


def split_patch(patch: str) -> list[FileDiff]:
    """Cut a multi-file patch into one entry per path."""
    out = []
    for chunk in re.split(r"(?m)^(?=diff --git )", patch):
        if not chunk.startswith("diff --git "):
            continue
        path, binary = _path_of(chunk)
        out.append(FileDiff(path, diff.parse(path, chunk), binary=binary))
    return out


async def repository_problem(root: Path) -> str:
    """Why there is nothing to diff here, or empty when Git and a repo exist."""
    code, text = await _git(root, "rev-parse", "--show-toplevel")
    if code == 127:
        return "Git is not installed."
    if code:
        return "No Git repository found."
    return ""


async def collect(root: Path) -> Snapshot:
    """Read the working tree's changes against HEAD, plus untracked files."""
    problem = await repository_problem(root)
    if problem:
        return Snapshot(error=problem)
    code, _ = await _git(root, "rev-parse", "--verify", "--quiet", "HEAD")
    base = "HEAD"
    if code:
        # No commits yet: compare against the empty tree for this repo's hash.
        code, empty = await _git(root, "hash-object", "-t", "tree", "--stdin", stdin=b"")
        base = empty.strip()
    diff_args = ("diff", "--no-color", "--no-ext-diff", "-M", "--relative", base, "--")
    (code, patch), (_, untracked) = await asyncio.gather(
        _git(root, *diff_args),
        _git(root, "ls-files", "--others", "--exclude-standard", "-z"))
    if code:
        return Snapshot(error=patch.strip() or "git diff failed")
    truncated = len(patch) > MAX_PATCH
    files = split_patch(patch[:MAX_PATCH])
    files.extend(FileDiff(name, untracked=True)
                 for name in sorted(filter(None, untracked.split("\0"))))
    error = "Patch too large; showing the first part." if truncated else ""
    return Snapshot(files=files, error=error, key=patch + "\0\0" + untracked)


class DiffRows(Widget):
    """A file's numbered rows, banded across the full panel width."""

    DEFAULT_CSS = """
    DiffRows { width: 1fr; height: auto; background: transparent; }
    """

    def __init__(self, change: diff.Change) -> None:
        super().__init__()
        self.view = diff.ChangeView(change)

    def get_content_height(self, container, viewport, width: int) -> int:
        return max(len(self.view.rows(width)) + bool(self.view.change.hidden), 1)

    def render(self) -> Text:
        width = max(self.size.width, 20)
        body = Text(no_wrap=True, overflow="crop")
        for index, line in enumerate(self.view.rows(width)):
            if index:
                body.append("\n")
            body.append_text(line)
        if self.view.change.hidden:
            body.append(f"\n  … {self.view.change.hidden} more lines", style="dim")
        return body


class FileListing(Widget):
    """Every changed path with its counts, laid out for the current width."""

    DEFAULT_CSS = """
    FileListing { width: 1fr; height: auto; background: transparent; }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.files: list[FileDiff] = []

    def show_files(self, files: list[FileDiff]) -> None:
        self.files = files
        self.display = bool(files)
        self.refresh(layout=True)

    def get_content_height(self, container, viewport, width: int) -> int:
        return max(len(self.files), 1)

    def render(self) -> Text:
        return _listing(self.files, max(self.size.width, 20))


class CloseMark(Static):
    """The × in the panel's corner."""

    DEFAULT_CSS = """
    CloseMark { width: 1; height: 1; background: transparent; }
    CloseMark:hover { text-style: bold reverse; }
    """

    def __init__(self) -> None:
        super().__init__(CLOSE)

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.screen.query_one(DiffPanel).hide()


class AskButton(Static):
    """Start a prompt about one file's changes."""

    DEFAULT_CSS = f"""
    AskButton {{ width: {len(ASK)}; height: 1; background: transparent; text-style: bold; }}
    AskButton:hover {{ text-style: bold reverse; }}
    """

    def __init__(self, path: str) -> None:
        super().__init__(Text(ASK))
        self.path = path

    def on_click(self, event: events.Click) -> None:
        event.stop()
        from .composer import Prompt
        prompt = self.app.query_one(Prompt)
        prompt._load(f"About my uncommitted changes in {self.path}: ")
        prompt.move_cursor(prompt.document.end)
        self.screen.query_one(DiffPanel).show_chat()
        prompt.focus()


class FileSection(Vertical):
    """Header and rows for one path."""

    DEFAULT_CSS = """
    FileSection { width: 1fr; height: auto; margin-top: 1; }
    FileSection > .head { width: 1fr; height: 1; }
    FileSection > .head > .name { width: 1fr; height: 1; }
    FileSection > .rule { width: 1fr; height: 1; color: $foreground 30%; }
    FileSection > .note { width: 1fr; height: auto; margin-top: 1; }
    """

    def __init__(self, item: FileDiff) -> None:
        super().__init__()
        self.item = item

    def compose(self):
        item = self.item
        name = Text(item.path, style="bold")
        if item.untracked:
            name.append(" (untracked)", style="dim")
        elif item.binary:
            name.append(" (binary)", style="dim")
        yield Static(Text("─" * 400, no_wrap=True, overflow="crop"), classes="rule")
        with Horizontal(classes="head"):
            yield Static(name, classes="name")
            yield AskButton(item.path)
        yield Static(Text("─" * 400, no_wrap=True, overflow="crop"), classes="rule")
        if item.untracked:
            yield Static(Text(f"New file not yet staged.\nRun `git add :/{item.path}` "
                              "to see line counts.", style="italic dim"), classes="note")
        elif item.binary or item.change is None or not item.change.rows:
            note = "Binary file changed." if item.binary else "Mode or metadata change only."
            yield Static(Text(note, style="italic dim"), classes="note")
        else:
            yield DiffRows(item.change)


class DiffPanel(VerticalScroll):
    """Uncommitted changes, docked to the right of the chat."""

    DEFAULT_CSS = """
    DiffPanel {
        split: right;
        width: 45%;
        min-width: 40;
        height: 1fr;
        padding: 0 1;
        background: $background;
        border-left: vkey $foreground 30%;
        scrollbar-size-vertical: 1;
        display: none;
    }
    /* Narrow windows: cover the chat rather than squeeze it. */
    DiffPanel.full {
        split: none;
        position: absolute;
        overlay: screen;
        layer: diff;
        width: 100%;
        min-width: 0;
        height: 100%;
        border-left: none;
    }
    DiffPanel > #diff-head { width: 1fr; height: 1; margin-top: 1; }
    DiffPanel > #diff-head > #diff-summary { width: 1fr; height: 1; }
    DiffPanel > #diff-list { width: 1fr; height: auto; margin-top: 1; }
    DiffPanel > #diff-files { width: 1fr; height: auto; margin-bottom: 1; }
    """

    BINDINGS: list = []
    can_focus = False

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root
        self._timer = None
        self._key: str | None = None
        self._busy = False
        self._again = False
        self._open = False
        self._narrow = False
        self._viewing = False

    def compose(self):
        with Horizontal(id="diff-head"):
            yield Static(Text("Loading changes…", style="dim"), id="diff-summary")
            yield CloseMark()
        yield FileListing(id="diff-list")
        yield Vertical(id="diff-files")

    @property
    def open(self) -> bool:
        return self._open

    @property
    def narrow(self) -> bool:
        return self._narrow

    def show(self) -> None:
        self._open = True
        if self._timer is None:
            self._timer = self.set_interval(REFRESH_SECONDS, self.reload)
        self.fit(self.app.size.width)

    def hide(self) -> None:
        self._open = False
        self._viewing = False
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self.fit(self.app.size.width)

    def fit(self, width: int) -> None:
        """Sit beside the chat when there is room, otherwise take turns with it."""
        self._narrow = width < NARROW_WIDTH
        full = self._narrow and self._viewing
        before = (bool(self.display), self.has_class("full"))
        self.set_class(full, "full")
        self.display = self._open and (full or not self._narrow)
        self.screen.query_one(DiffToggle).place(self, width)
        if self.display and before != (True, full):
            # Redraw once the new width is laid out, so the listing fits it.
            self._key = None
            self.call_after_refresh(self.reload)

    def show_diff(self) -> None:
        self._viewing = True
        self.fit(self.app.size.width)

    def show_chat(self) -> None:
        self._viewing = False
        self.fit(self.app.size.width)

    def flip(self) -> None:
        self._viewing = not self._viewing
        self.fit(self.app.size.width)

    def toggle(self) -> bool:
        if self.open:
            self.hide()
        else:
            self.show()
        return self.open

    def reload(self) -> None:
        """Re-read Git in the background; skip if a read is still running."""
        if not self.display:
            return
        if self._busy:
            self._again = True
            return
        self._busy = True
        self.run_worker(self._reload(), group="diff-panel", exclusive=True)

    async def _reload(self) -> None:
        try:
            snapshot = await collect(self.root)
        except OSError as exc:
            snapshot = Snapshot(error=str(exc))
        finally:
            self._busy = False
        key = snapshot.key or snapshot.error
        if key != self._key:
            self._key = key
            await self._draw(snapshot)
        if self._again:
            # A resize may have landed mid-read; draw again at the new width.
            self._again = False
            self._key = None
            self.reload()

    async def _draw(self, snapshot: Snapshot) -> None:
        summary = self.query_one("#diff-summary", Static)
        listing = self.query_one(FileListing)
        holder = self.query_one("#diff-files", Vertical)
        await holder.remove_children()
        if not snapshot.files:
            summary.update(Text(snapshot.error or "No uncommitted changes.",
                                style="dim" if not snapshot.error else palette.RED))
            listing.show_files([])
            return
        count = len(snapshot.files)
        head = Text()
        head.append(f"{count} file{'s' if count != 1 else ''}", style="bold")
        head.append(" changed ")
        head.append(f"+{snapshot.added}", style=palette.GREEN)
        head.append(" ")
        head.append(f"-{snapshot.removed}", style=palette.RED)
        if snapshot.error:
            head.append(f"  {snapshot.error}", style="dim")
        summary.update(head)
        listing.show_files(snapshot.files)
        await holder.mount_all([FileSection(item) for item in snapshot.files])

    def on_resize(self, event: events.Resize) -> None:
        self._key = None
        self.reload()


class DiffToggle(Static):
    """Top-right switch between the chat and the diff on narrow terminals."""

    DEFAULT_CSS = """
    DiffToggle {
        position: absolute;
        overlay: screen;
        layer: diff;
        width: auto;
        height: 1;
        /* Arrows are double width in some terminals; the spare right cell
           absorbs the shift so nothing spills past the button and smears. */
        padding: 0 2 0 1;
        color: $text;
        background: $foreground 15%;
        text-style: bold;
        display: none;
    }
    DiffToggle:hover { text-style: bold reverse; }
    """

    def __init__(self) -> None:
        super().__init__("")

    def place(self, panel: DiffPanel, width: int) -> None:
        self.display = panel.open and panel.narrow
        if not self.display:
            return
        label = TO_CHAT if panel.has_class("full") else TO_DIFF
        self.update(label)
        # Keep clear of the rightmost column, where the scrollbars sit.
        self.styles.offset = (max(width - len(label) - 4, 0), 0)

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.screen.query_one(DiffPanel).flip()


def _listing(files: list[FileDiff], width: int) -> Text:
    """Path on the left, counts flush right."""
    body = Text(no_wrap=True, overflow="ellipsis")
    for index, item in enumerate(files):
        counts = Text()
        if item.added:
            counts.append(f"+{item.added}", style=palette.GREEN)
        if item.removed:
            if counts:
                counts.append(" ")
            counts.append(f"-{item.removed}", style=palette.RED)
        name = Text(item.path, style="dim" if item.untracked else "")
        room = max(width - counts.cell_len - 1, 8)
        name.truncate(room, overflow="ellipsis")
        if index:
            body.append("\n")
        body.append_text(name)
        body.append(" " * max(width - name.cell_len - counts.cell_len, 1))
        body.append_text(counts)
    return body
