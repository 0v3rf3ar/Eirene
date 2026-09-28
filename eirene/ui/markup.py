"""Markdown, rendered for the terminal."""

from __future__ import annotations

import re

from rich.console import Console, ConsoleOptions, RenderResult
from rich.syntax import Syntax
from rich.text import Text

from .palette import CODE_THEME, CYAN

SYNTAX_THEME = CODE_THEME
CODE_STYLE = "#f0f6fc on #3b4149"
BORDER_STYLE = "dim"
LABEL_STYLE = "dim"
LINK_STYLE = f"underline {CYAN}"
QUOTE_STYLE = "dim italic"
DEFAULT_WIDTH = 88
PROSE_WIDTH = 88
WRAP_CONSOLE = Console(color_system=None)

FENCE = re.compile(r"^\s*(?:```|~~~)\s*([\w+#.-]*)\s*$")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
ORDERED = re.compile(r"^(\s*)(\d+[.)])\s+(.*)$")
QUOTE = re.compile(r"^\s*>\s?(.*)$")
RULE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")

INLINE = re.compile(
    r"(?P<ticks>`+)(?P<code>.+?)(?P=ticks)"
    r"|<(?:u|ins)>(?P<uline>.+?)</(?:u|ins)>"
    r"|\+\+(?P<uline2>\S(?:.*?\S)?)\+\+"
    r"|<(?:b|strong)>(?P<strong3>.+?)</(?:b|strong)>"
    r"|<(?:i|em)>(?P<em3>.+?)</(?:i|em)>"
    r"|<(?:s|del|strike)>(?P<strike2>.+?)</(?:s|del|strike)>"
    r"|\*\*(?P<strong>\S(?:.*?\S)?)\*\*"
    r"|__(?P<strong2>\S(?:.*?\S)?)__"
    r"|(?<![\w*])\*(?P<em>[^*\s](?:[^*]*[^*\s])?)\*(?![\w*])"
    r"|(?<![\w_])_(?P<em2>[^_\s](?:[^_]*[^_\s])?)_(?![\w_])"
    r"|~~(?P<strike>\S(?:.*?\S)?)~~"
    r"|\[(?P<label>[^\]\n]+)\]\((?P<url>[^)\s]+)\)"
)

STYLES = {
    "code": CODE_STYLE,
    "uline": "underline", "uline2": "underline",
    "strong": "bold", "strong2": "bold", "strong3": "bold",
    "em": "italic", "em2": "italic", "em3": "italic",
    "strike": "strike", "strike2": "strike",
}


def set_code_style(style: str | None = None) -> None:
    """Colour inline code spans for the current theme, or reset to the default."""
    STYLES["code"] = style or CODE_STYLE


BULLET_MARK = "•"

ROW = re.compile(r"^\s*\|(?P<body>.*)\|\s*$")
DIVIDER = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")
CELL_SPLIT = re.compile(r"(?<!\\)\|")
MAX_CELL = 44


def inline(text: str) -> Text:
    """One line of prose, with the markers applied."""
    body = Text()
    position = 0
    for match in INLINE.finditer(text):
        if match.start() > position:
            body.append(text[position:match.start()])
        groups = match.groupdict()
        if groups["label"] is not None:
            body.append(groups["label"], style=LINK_STYLE)
            body.append(f" ({groups['url']})", style="dim")
        else:
            for name, style in STYLES.items():
                if groups.get(name) is not None:
                    body.append(groups[name], style=style)
                    break
        position = match.end()
    if position < len(text):
        body.append(text[position:])
    return body


def block(line: str) -> Text:
    """One line of markdown, outside a fence."""
    if RULE.match(line):
        return Text("─" * 24, style="dim")
    heading = HEADING.match(line)
    if heading:
        body = inline(heading.group(2))
        body.stylize("bold" if len(heading.group(1)) > 1 else "bold underline")
        return body
    quote = QUOTE.match(line)
    if quote:
        body = Text()
        body.append("│ ", style="dim")
        body.append_text(inline(quote.group(1)))
        body.stylize(QUOTE_STYLE, 2)
        return body
    bullet = BULLET.match(line)
    if bullet:
        body = Text()
        body.append(f"{bullet.group(1)}{BULLET_MARK} ", style="dim")
        body.append_text(inline(bullet.group(2)))
        return body
    ordered = ORDERED.match(line)
    if ordered:
        body = Text()
        body.append(f"{ordered.group(1)}{ordered.group(2)} ", style="dim")
        body.append_text(inline(ordered.group(3)))
        return body
    return inline(line)


def cells(line: str) -> list[str]:
    """Split one table row into its cells."""
    match = ROW.match(line)
    body = match.group("body") if match else line.strip().strip("|")
    return [cell.replace("\\|", "|").strip() for cell in CELL_SPLIT.split(body)]


def alignments(divider: str) -> list[str]:
    """Left, right or centre, per column."""
    out = []
    for cell in cells(divider):
        mark = cell.strip()
        if mark.startswith(":") and mark.endswith(":"):
            out.append("centre")
        elif mark.endswith(":"):
            out.append("right")
        else:
            out.append("left")
    return out


def _fit(text: Text, width: int, align: str) -> Text:
    """Pad or trim one cell to the column width."""
    body = text.copy()
    if body.cell_len > width:
        body.truncate(max(width - 1, 1), overflow="ellipsis")
    room = width - body.cell_len
    if room <= 0:
        return body
    if align == "right":
        return Text(" " * room).append_text(body)
    if align == "centre":
        left = room // 2
        return Text(" " * left).append_text(body).append(" " * (room - left))
    body.append(" " * room)
    return body


def table(source: list[str], start: int) -> tuple[list[Text], int] | None:
    """Render a markdown table, or None if there is not one here."""
    if start + 1 >= len(source):
        return None
    divider = source[start + 1]
    if not ROW.match(source[start]) or "|" not in divider:
        return None
    if not DIVIDER.match(divider):
        return None
    header = cells(source[start])
    align = alignments(source[start + 1])
    if len(align) != len(header):
        return None

    rows = []
    index = start + 2
    while index < len(source) and ROW.match(source[index]):
        rows.append(cells(source[index]))
        index += 1

    columns = len(header)
    grid = [header] + [row + [""] * (columns - len(row)) for row in rows]
    drawn = [[inline(cell) for cell in row[:columns]] for row in grid]
    widths = [min(max((row[column].cell_len for row in drawn), default=3), MAX_CELL)
              for column in range(columns)]

    out = [_rule("┌", "┬", "┐", widths)]
    head = Text("│ ", style="dim")
    for column, cell in enumerate(drawn[0]):
        piece = _fit(cell, widths[column], align[column])
        piece.stylize("bold")
        head.append_text(piece)
        head.append(" │ " if column < columns - 1 else " │", style="dim")
    out.append(head)
    out.append(_rule("├", "┼", "┤", widths))
    for row in drawn[1:]:
        line = Text("│ ", style="dim")
        for column, cell in enumerate(row):
            line.append_text(_fit(cell, widths[column], align[column]))
            line.append(" │ " if column < columns - 1 else " │", style="dim")
        out.append(line)
    out.append(_rule("└", "┴", "┘", widths))
    return out, index - start


def _rule(left: str, join: str, right: str, widths: list[int]) -> Text:
    bars = join.join("─" * (width + 2) for width in widths)
    return Text(f"{left}{bars}{right}", style="dim")


def code_block(source: list[str], start: int, width: int) -> tuple[list[Text], int]:
    """A transparent fenced block with its language in the top border."""
    language = (FENCE.match(source[start]).group(1) or "").strip()
    body: list[str] = []
    index = start + 1
    while index < len(source) and not FENCE.match(source[index]):
        body.append(source[index])
        index += 1
    if index < len(source):
        index += 1

    syntax = Syntax("", language or "text", theme=SYNTAX_THEME,
                    background_color="default")
    inner_width = max(width - 4, 1)
    shown_language = language[:max(width - 6, 1)]
    title = f"─ {shown_language} " if shown_language else "─"
    top = Text("╭", style=BORDER_STYLE)
    top.append(title, style=LABEL_STYLE if language else BORDER_STYLE)
    top.append("─" * max(width - top.cell_len - 1, 0), style=BORDER_STYLE)
    top.append("╮", style=BORDER_STYLE)
    out: list[Text] = [top]
    for line in body or [""]:
        try:
            code = syntax.highlight(line)
            code.remove_suffix("\n")
        except Exception:  # noqa: BLE001
            code = Text(line)
        if code.cell_len > inner_width:
            code.truncate(inner_width, overflow="ellipsis")
        _pad(code, inner_width)
        row = Text("│ ", style=BORDER_STYLE)
        row.append_text(code)
        row.append(" │", style=BORDER_STYLE)
        out.append(row)
    out.append(Text(f"╰{'─' * max(width - 2, 0)}╯", style=BORDER_STYLE))
    return out, index - start


def _pad(line: Text, width: int) -> None:
    room = width - line.cell_len
    if room > 0:
        line.append(" " * room)


def prose_lines(line: str, width: int) -> list[Text]:
    """Wrap styled prose, keeping list and quote continuation lines aligned."""
    body = block(line)
    bullet = BULLET.match(line)
    ordered = ORDERED.match(line)
    quote = QUOTE.match(line)
    prefix_length = (len(bullet.group(1)) + 2 if bullet else
                     len(ordered.group(1)) + len(ordered.group(2)) + 1 if ordered else
                     2 if quote else len(body.plain) - len(body.plain.lstrip()))
    prefix = body[:prefix_length]
    # Preserve room for text even in a deeply nested list on a narrow terminal.
    if prefix.cell_len >= width:
        prefix = Text(" " * max(0, width - 3))
    continuation = Text("│ ", style="dim") if quote else Text(" " * prefix.cell_len)
    wrapped = body[prefix_length:].wrap(WRAP_CONSOLE, max(1, width - prefix.cell_len),
                                         overflow="fold", no_wrap=False)
    rows = []
    for index, part in enumerate(wrapped):
        part.rstrip()
        rows.append((prefix.copy() if index == 0 else continuation.copy()).append_text(part))
    return rows or [Text("")]


class Markdown:
    """Prose with markdown applied and fenced code highlighted."""

    def __init__(self, body: str, width: int = DEFAULT_WIDTH):
        self.body = body
        self.width = max(int(width or DEFAULT_WIDTH), 4)

    def lines(self) -> list[Text]:
        """Every rendered line, in order."""
        out: list[Text] = []
        source = self.body.splitlines() or [""]
        index = 0
        previous_list = False
        previous_wrapped = False
        while index < len(source):
            line = source[index]
            if FENCE.match(line):
                rendered, used = code_block(source, index, self.width)
                out.extend(rendered)
                index += used
                previous_list = False
                continue
            drawn = table(source, index)
            if drawn is not None:
                rendered, used = drawn
                out.extend(rendered)
                index += used
                previous_list = False
                continue
            rendered = prose_lines(line, min(self.width, PROSE_WIDTH))
            is_list = bool((BULLET.match(line) or ORDERED.match(line)) and not RULE.match(line))
            if out and out[-1].plain.strip() and line.strip():
                # Long list items need breathing room. Short checklists stay compact.
                if ((is_list and previous_list and (previous_wrapped or len(rendered) > 1))
                        or (is_list and not previous_list)
                        or (previous_list and not is_list and not line[:1].isspace())):
                    out.append(Text(""))
            if line.strip() or not out or out[-1].plain.strip():
                out.extend(rendered)
            if HEADING.match(line) and index + 1 < len(source):
                out.append(Text(""))
            previous_list = is_list
            previous_wrapped = len(rendered) > 1
            index += 1
        return out

    def text(self) -> Text:
        """One Text, so the mouse can select inside it."""
        body = Text()
        for index, line in enumerate(self.lines()):
            if index:
                body.append("\n")
            body.append_text(line)
        return body

    def plain(self) -> str:
        """What the block reads as, for copying."""
        return "\n".join(line.plain for line in self.lines())

    def __rich_console__(self, console: Console,
                         options: ConsoleOptions) -> RenderResult:
        yield from Markdown(self.body, min(self.width, options.max_width)).lines()


def render(body: str, width: int = DEFAULT_WIDTH) -> Text:
    """Markdown as a single selectable Text."""
    return Markdown(body, width).text()


def trim(text: str) -> str:
    """Drop padding and a selected fenced-code edge."""
    lines = []
    for line in text.splitlines():
        cleaned = line.rstrip()
        if cleaned.startswith("│ "):
            cleaned = cleaned[2:]
        if cleaned.endswith(" │"):
            cleaned = cleaned[:-2].rstrip()
        lines.append(cleaned)
    return "\n".join(lines)
