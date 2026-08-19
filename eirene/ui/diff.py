"""Reading unified diffs and drawing them."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rich.console import Console, ConsoleOptions, RenderResult
from rich.syntax import Syntax
from rich.text import Text

from . import art, palette

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
MAX_ROWS = 120
ADDED_BACKGROUND = "on #0e2b16"
REMOVED_BACKGROUND = "on #3d1214"
ADDED_GUTTER = palette.GREEN
REMOVED_GUTTER = palette.RED
SYNTAX_THEME = palette.CODE_THEME
GUTTER = 3

LEXERS = {
    ".py": "python", ".pyi": "python", ".js": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "tsx", ".jsx": "jsx", ".json": "json",
    ".toml": "toml", ".yaml": "yaml", ".yml": "yaml", ".md": "markdown",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash", ".fish": "fish",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".rs": "rust",
    ".go": "go", ".rb": "ruby", ".java": "java", ".kt": "kotlin",
    ".php": "php", ".sql": "sql", ".html": "html", ".css": "css",
    ".scss": "scss", ".xml": "xml", ".ini": "ini", ".cfg": "ini",
    ".service": "ini", ".timer": "ini", ".lua": "lua", ".pl": "perl",
    ".swift": "swift", ".dockerfile": "docker", ".tf": "terraform",
}


def strip_gutter(text: str, width: int) -> str:
    """Drop the number and sign columns, keeping the code."""
    out = []
    for line in text.splitlines():
        if len(line) >= width and re.fullmatch(r"\s*\d*\s*[-+]?\s?", line[:width]):
            out.append(line[width:].rstrip())
        else:
            out.append(line.rstrip())
    return "\n".join(out)


def lexer_for(path: str) -> str:
    """Pygments name for a file, or plain text."""
    name = str(path).lower()
    if name.endswith("dockerfile") or "/dockerfile" in name:
        return "docker"
    if name.endswith("makefile"):
        return "make"
    for suffix, lexer in LEXERS.items():
        if name.endswith(suffix):
            return lexer
    return "text"


@dataclass
class Row:
    """One line of a change."""

    sign: str
    text: str
    number: int | None = None


@dataclass
class Change:
    """A pending or finished file change."""

    path: str
    action: str = "Update"
    added: int = 0
    removed: int = 0
    rows: list[Row] = field(default_factory=list)
    hidden: int = 0

    @property
    def summary(self) -> str:
        parts = [f"Added {self.added} line{'' if self.added == 1 else 's'}"]
        parts.append(f"removed {self.removed} line{'' if self.removed == 1 else 's'}")
        return ", ".join(parts)


def parse(path: str, diff: str, action: str = "") -> Change:
    """Read a unified diff into rows."""
    change = Change(path=path, action=action or "Update")
    old_line = new_line = 0
    started = False
    for line in (diff or "").splitlines():
        match = HUNK.match(line)
        if match:
            old_line = int(match.group(1))
            new_line = int(match.group(3))
            started = True
            continue
        if line.startswith(("--- ", "+++ ", "diff ", "index ")):
            continue
        if not started:
            continue
        if line.startswith("+"):
            change.rows.append(Row("+", line[1:], new_line))
            change.added += 1
            new_line += 1
        elif line.startswith("-"):
            change.rows.append(Row("-", line[1:], old_line))
            change.removed += 1
            old_line += 1
        elif line.startswith("\\"):
            continue
        else:
            change.rows.append(Row(" ", line[1:] if line else "", new_line))
            old_line += 1
            new_line += 1
    if not started:
        change = _loose(path, diff, action)
    if len(change.rows) > MAX_ROWS:
        change.hidden = len(change.rows) - MAX_ROWS
        change.rows = change.rows[:MAX_ROWS]
    return change


def _loose(path: str, diff: str, action: str) -> Change:
    """Fall back to a bare +/- listing."""
    change = Change(path=path, action=action or "Update")
    for line in (diff or "").splitlines():
        if line.startswith("+ "):
            change.rows.append(Row("+", line[2:]))
            change.added += 1
        elif line.startswith("- "):
            change.rows.append(Row("-", line[2:]))
            change.removed += 1
        else:
            change.rows.append(Row(" ", line))
    return change


class ChangeView:
    """Numbered, highlighted, colour-banded diff."""

    def __init__(self, change: Change, note: str = ""):
        self.change = change
        self.note = note
        self.syntax = Syntax("", lexer_for(change.path), theme=SYNTAX_THEME,
                             background_color="default")

    def _code(self, text: str) -> Text:
        try:
            body = self.syntax.highlight(text or "")
        except Exception:  # noqa: BLE001
            return Text(text or "")
        body.remove_suffix("\n")
        return body

    def gutter(self) -> int:
        """Width of the number and sign columns."""
        digits = max((len(str(row.number or 0)) for row in self.change.rows),
                     default=GUTTER)
        return max(digits, GUTTER) + 4

    def text(self, width: int) -> Text:
        """One Text, so the mouse can select inside it."""
        body = Text(no_wrap=True, overflow="crop")
        for index, line in enumerate(self.lines(width)):
            if index:
                body.append("\n")
            body.append_text(line)
        return body

    def lines(self, width: int) -> list[Text]:
        """Every rendered line, in order."""
        out = [self._head(), self._summary()]
        out.extend(self.rows(width))
        if self.change.hidden:
            out.append(Text(f"  … {self.change.hidden} more lines", style="dim"))
        if self.note:
            out.append(Text(f"  {self.note}", style="bold"))
        return out

    def plain(self, width: int) -> str:
        """What the block reads as, for copying."""
        return "\n".join(line.plain for line in self.lines(width))

    def rows(self, width: int) -> list[Text]:
        """The numbered code lines."""
        out = []
        digits = self.gutter() - 4
        for row in self.change.rows:
            line = Text()
            number = str(row.number) if row.number else ""
            style = ADDED_GUTTER if row.sign == "+" else (
                REMOVED_GUTTER if row.sign == "-" else "dim")
            line.append(f" {number:>{digits}} ", style=style)
            line.append(f"{row.sign} " if row.sign != " " else "  ", style=style)
            line.append_text(self._code(row.text))
            if row.sign != " ":
                pad = width - line.cell_len
                if pad > 0:
                    line.append(" " * pad)
                line.stylize(ADDED_BACKGROUND if row.sign == "+"
                             else REMOVED_BACKGROUND)
            out.append(line)
        return out

    def _head(self) -> Text:
        change = self.change
        head = Text()
        head.append(f"{art.icon('bullet')} ", style=ADDED_GUTTER)
        head.append(change.action, style="bold")
        head.append("(")
        head.append(change.path, style="underline")
        head.append(")")
        return head

    def _summary(self) -> Text:
        change = self.change
        summary = Text()
        summary.append(f"{art.icon('corner')} ", style="dim")
        summary.append("Added ", style="dim")
        summary.append(str(change.added), style="bold")
        summary.append(" line" if change.added == 1 else " lines", style="dim")
        summary.append(", removed ", style="dim")
        summary.append(str(change.removed), style="bold")
        summary.append(" line" if change.removed == 1 else " lines", style="dim")
        return summary

    def __rich_console__(self, console: Console,
                         options: ConsoleOptions) -> RenderResult:
        yield from self.lines(max(options.max_width, 20))
