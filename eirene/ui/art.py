"""ASCII art, icons and spinner frames."""

from __future__ import annotations

import random

from rich.cells import cell_len

BANNERS = [
    r"""
 ▄███▄   ▄█ █▄▄▄▄ ▄███▄      ▄   ▄███▄
█▀   ▀  ██ █  ▄▀ █▀   ▀      █  █▀   ▀
██▄▄    ██ █▀▀▌  ██▄▄    ██   █ ██▄▄
█▄   ▄▀ ▐█ █  █  █▄   ▄▀ █ █  █ █▄   ▄▀
▀███▀    ▐   █   ▀███▀   █  █ █ ▀███▀
            ▀            █   ██
""",
    r"""
┏━╸╻┏━┓┏━╸┏┓╻┏━╸
┣╸ ┃┣┳┛┣╸ ┃┗┫┣╸
┗━╸╹╹┗╸┗━╸╹ ╹┗━╸
""",
    r"""
░█▀▀░▀█▀░█▀▄░█▀▀░█▀█░█▀▀
░█▀▀░░█░░█▀▄░█▀▀░█░█░█▀▀
░▀▀▀░▀▀▀░▀░▀░▀▀▀░▀░▀░▀▀▀
""",
    r"""
██████ ▄▄ ▄▄▄▄  ▄▄▄▄▄ ▄▄  ▄▄ ▄▄▄▄▄
██▄▄   ██ ██▄█▄ ██▄▄  ███▄██ ██▄▄
██▄▄▄▄ ██ ██ ██ ██▄▄▄ ██ ▀██ ██▄▄▄
""",
    r"""
▓█████  ██▓ ██▀███  ▓█████  ███▄    █ ▓█████
▓█   ▀ ▓██▒▓██ ▒ ██▒▓█   ▀  ██ ▀█   █ ▓█   ▀
▒███   ▒██▒▓██ ░▄█ ▒▒███   ▓██  ▀█ ██▒▒███
▒▓█  ▄ ░██░▒██▀▀█▄  ▒▓█  ▄ ▓██▒  ▐▌██▒▒▓█  ▄
░▒████▒░██░░██▓ ▒██▒░▒████▒▒██░   ▓██░░▒████▒
░░ ▒░ ░░▓  ░ ▒▓ ░▒▓░░░ ▒░ ░░ ▒░   ▒ ▒ ░░ ▒░ ░
 ░ ░  ░ ▒ ░  ░▒ ░ ▒░ ░ ░  ░░ ░░   ░ ▒░ ░ ░  ░
   ░    ▒ ░  ░░   ░    ░      ░   ░ ░    ░
   ░  ░ ░     ░        ░  ░         ░    ░  ░
""",
    r"""
▄▄▄ .▪  ▄▄▄  ▄▄▄ . ▐ ▄ ▄▄▄ .
▀▄.▀·██ ▀▄ █·▀▄.▀·•█▌▐█▀▄.▀·
▐▀▀▪▄▐█·▐▀▀▄ ▐▀▀▪▄▐█▐▐▌▐▀▀▪▄
▐█▄▄▌▐█▌▐█•█▌▐█▄▄▌██▐█▌▐█▄▄▌
 ▀▀▀ ▀▀▀.▀  ▀ ▀▀▀ ▀▀ █▪ ▀▀▀
""",
]

ANIMATIONS = ("scramble", "drip", "stars")

DRIP_GLYPHS = "●•"
STAR_GLYPHS = ".·▪•"
# A dot swells and fades again, the way a star seems to breathe.
STAR_SIZES = ("·", "•", "●", "•")
DROPS_IN_FLIGHT = 2
DROP_CYCLE = 16
# The bloody banner bleeds; the dotted one twinkles; the rest reassemble.
DRIP_BANNER, STAR_BANNER = 4, 5

SMALL_BANNER = r"""
╭──────────────╮
│  e i r e n e │
╰──────────────╯
"""

TINY_BANNER = "e i r e n e"

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
ACCESSIBLE = False

ICONS = {
    "prompt": "\u276f",
    "user": "◇", "agent": "◆", "think": "✦", "file": "▤",
    "write": "▣", "edit": "✎", "read": "◉", "dir": "▰",
    "search": "⌕", "shell": "⌘", "ok": "✓", "fail": "✗",
    "warn": "⚠︎", "info": "ⓘ", "clock": "◷",
    "tokens": "\u2193",
    "up": "\u2191",
    "auto": "⚡︎",
    "manual": "\u23f8",
    "plan": "☷", "skill": "◆", "task": "▦", "link": "↗",
    "dot": "\u00b7",
    "arrow": "\u2192",
    "bullet": "\u25cf",
    "corner": "\u2514",
}
ASCII_ICONS = {
    "prompt": ">", "user": "U", "agent": "A", "think": "?",
    "file": "F", "write": "W", "edit": "E", "read": "R", "dir": "D",
    "search": "S", "shell": "$", "ok": "+", "fail": "x", "warn": "!",
    "info": "i", "clock": "t", "tokens": "v", "up": "^", "auto": "A",
    "manual": "M", "plan": "P", "skill": "K", "task": "T", "link": "@",
    "dot": ".", "arrow": "->", "bullet": "*", "corner": "`",
}

TOOL_ICONS = {
    "read_file": ICONS["read"],
    "read_image": ICONS["file"],
    "write_file": ICONS["write"],
    "edit_file": ICONS["edit"],
    "list_dir": ICONS["dir"],
    "glob": ICONS["search"],
    "run_command": ICONS["shell"],
}

# Claude Code and Codex name their own tools; show them with Eirene's icons.
NATIVE_TOOLS = {
    "Read": "read_file", "NotebookRead": "read_file", "Write": "write_file",
    "Edit": "edit_file", "MultiEdit": "edit_file", "NotebookEdit": "edit_file",
    "Bash": "run_command", "BashOutput": "run_command", "KillShell": "run_command",
    "Glob": "glob", "Grep": "glob", "LS": "list_dir",
}

# Box-drawing pieces used by the intro panel, tinted by themes with an accent.
RULE_GLYPHS = "─┬┴│"

FOLDER_ICON = "▰"
PLAIN_FILE_ICON = "▤"

VERBS = [
    "Pollinating", "Percolating", "Untangling", "Rummaging", "Marinating",
    "Whittling", "Tinkering", "Conjuring", "Simmering", "Wrangling",
    "Noodling", "Sifting", "Puzzling", "Distilling", "Cogitating",
]

TIPS = [
    "Press shift+tab to switch between manual, auto, and plan modes.",
    "Use /btw for a quick side question without changing the main conversation.",
    "Drag over any transcript text, then press ctrl+shift+c to copy it.",
    "Click the running-command bar to inspect or stop active commands.",
    "Use /review for a read-only review of the current working-tree changes.",
    "Use /sessions to search, resume, export, or import earlier conversations.",
    "Durable plans survive restarts; open the current one with /plan.",
    "Use esc to cancel the current turn without leaving the application.",
    "Press ctrl+e to jump back to the end of the transcript.",
]


def icon(name: str) -> str:
    table = ASCII_ICONS if ACCESSIBLE else ICONS
    return table.get(name, table["dot"])


def set_accessible(enabled: bool) -> None:
    global ACCESSIBLE
    ACCESSIBLE = bool(enabled)


def tool_icon(name: str) -> str:
    canonical = NATIVE_TOOLS.get(name, name)
    if ACCESSIBLE:
        return {"read_file": "R", "write_file": "W", "edit_file": "E",
                "list_dir": "D", "glob": "S", "run_command": "$"}.get(canonical, "i")
    return TOOL_ICONS.get(canonical, ICONS["info"])


def file_icon(path: str) -> str:
    """Portable monochrome symbol for a file or directory."""
    if ACCESSIBLE:
        return "F"
    text = str(path or "").strip().replace("\\", "/").rstrip("/")
    return FOLDER_ICON if not text else PLAIN_FILE_ICON


def spinner_frame(tick: int) -> str:
    return "*" if ACCESSIBLE else SPINNER[tick % len(SPINNER)]


def verb(seed: int | None = None) -> str:
    if seed is None:
        return random.choice(VERBS)
    return VERBS[seed % len(VERBS)]


def tip(seed: int | None = None) -> str:
    """A useful startup hint, stable when a seed is supplied."""
    if seed is None:
        return random.choice(TIPS)
    return TIPS[seed % len(TIPS)]


def art_width(text: str) -> int:
    """Widest rendered line, in terminal cells."""
    return max((cell_len(line) for line in text.strip("\n").splitlines()), default=0)


def banner_animation(text: str) -> str:
    """Return the stable, banner-specific click animation."""
    picture = text.strip("\n")
    for index, banner_art in enumerate(BANNERS):
        if picture.startswith(banner_art.strip("\n")):
            if index == DRIP_BANNER:
                return "drip"
            if index == STAR_BANNER:
                return "stars"
            return "scramble"
    return "scramble"


def scramble_frame(lines: list[str], tick: int, span: int) -> list[str]:
    """Glyphs shuffled along their row, settling back into place."""
    if span <= 0 or tick >= span:
        return list(lines)
    progress = tick / span
    frame = []
    for row, line in enumerate(lines):
        columns = [index for index, glyph in enumerate(line) if glyph != " "]
        if not columns:
            frame.append(line)
            continue
        shuffled = list(columns)
        random.Random(row * 977 + 13).shuffle(shuffled)
        cells = [" "] * len(line)
        for index, column in enumerate(columns):
            origin = shuffled[index]
            eased = min(max(progress * 1.6 - (index % 5) * 0.11, 0.0), 1.0)
            wanted = round(origin + (column - origin) * eased)
            cells[_free_slot(cells, wanted)] = line[column]
        frame.append("".join(cells))
    return frame


def _free_slot(cells: list[str], wanted: int) -> int:
    """Nearest empty column, so travelling glyphs never overwrite each other."""
    wanted = max(0, min(wanted, len(cells) - 1))
    if cells[wanted] == " ":
        return wanted
    for offset in range(1, len(cells)):
        for candidate in (wanted - offset, wanted + offset):
            if 0 <= candidate < len(cells) and cells[candidate] == " ":
                return candidate
    return wanted


def drip_frame(lines: list[str], tick: int) -> list[str]:
    """One or two discrete drops falling clear of the glyphs they left."""
    rows = [list(line) for line in lines]
    width = max((len(row) for row in rows), default=0)
    for row in rows:
        row.extend(" " * (width - len(row)))
    spouts = _spouts(rows, width)
    if not spouts:
        return lines
    for slot in range(DROPS_IN_FLIGHT):
        moment = tick + slot * (DROP_CYCLE // DROPS_IN_FLIGHT)
        column, bottom = spouts[(moment // DROP_CYCLE + slot * 3) % len(spouts)]
        fallen = (moment % DROP_CYCLE) // 2
        if not fallen:
            continue
        target = bottom + fallen
        if target < len(rows) and rows[target][column] == " ":
            rows[target][column] = DRIP_GLYPHS[slot]
    return ["".join(row).rstrip() for row in rows]


def _spouts(rows: list[list[str]], width: int) -> list[tuple[int, int]]:
    """Columns a drop can leave from, with the row it hangs off."""
    found = []
    for column in range(width):
        filled = [index for index, row in enumerate(rows) if row[column] != " "]
        if filled and filled[-1] + 1 < len(rows):
            found.append((column, filled[-1]))
    return found


def star_frame(lines: list[str], tick: int) -> tuple[list[str], set[tuple[int, int]]]:
    """Swell the dotted glyphs in turn, and say which are at full glow."""
    rows = [list(line) for line in lines]
    glowing: set[tuple[int, int]] = set()
    for row, line in enumerate(rows):
        for column, glyph in enumerate(line):
            if glyph not in STAR_GLYPHS:
                continue
            phase = (column * 5 + row * 3 + tick // 3) % 12
            if phase >= len(STAR_SIZES):
                continue
            rows[row][column] = STAR_SIZES[phase]
            if STAR_SIZES[phase] == "●":
                glowing.add((row, column))
    return ["".join(row) for row in rows], glowing


SIZED = sorted(((picture.strip("\n"), art_width(picture))
                for picture in BANNERS), key=lambda pair: pair[1])
SMALL_WIDTH = art_width(SMALL_BANNER)
TINY_WIDTH = cell_len(TINY_BANNER)
BANNER_MARGIN = 4


def banner(width: int, margin: int = BANNER_MARGIN) -> str:
    """Choose a random banner that fits without wrapping."""
    room = width - margin
    if ACCESSIBLE:
        return TINY_BANNER if TINY_WIDTH <= room else "eirene"
    options = [text for text, size in SIZED if size <= room]
    if options:
        return random.choice(options)
    if SMALL_WIDTH <= room:
        return SMALL_BANNER.strip("\n")
    if TINY_WIDTH <= room:
        return TINY_BANNER
    return "eirene"
