"""ASCII art, icons and spinner frames."""

from __future__ import annotations

import math
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

EFFECTS = ("ignite", "ripple", "glitch", "rain", "assemble", "scan")

# Each banner opens with the effect that suits its shape; clicking again
# steps through the rest.
SIGNATURES = ("ignite", "scan", "rain", "glitch", "ripple", "assemble")

EFFECT_SPANS = {"ignite": 60, "ripple": 72, "glitch": 66, "rain": 96,
                "assemble": 66, "scan": 60}

RAIN_GLYPHS = "01╎╏┆┊"
NOISE_GLYPHS = "░▒▓"
GLITCH_GLYPHS = "▚▞▐▌▄▀▓▒"
SCAN_BAR = "│"

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
    "auto": "↯",
    "manual": "\u23f8",
    "plan": "☑", "skill": "⚙", "task": "⚑", "link": "↗",
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
    "Press shift + tab to change mode (manual, auto, or plan).",
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


Heat = dict[tuple[int, int], float]


def banner_index(text: str) -> int:
    picture = text.strip("\n")
    for index, banner_art in enumerate(BANNERS):
        if picture.startswith(banner_art.strip("\n")):
            return index
    return -1


def banner_animation(text: str) -> str:
    """The effect a banner opens with."""
    index = banner_index(text)
    return SIGNATURES[index] if index >= 0 else EFFECTS[0]


def next_animation(current: str) -> str:
    order = list(EFFECTS)
    if current not in order:
        return order[0]
    return order[(order.index(current) + 1) % len(order)]


def effect_span(effect: str) -> int:
    return EFFECT_SPANS.get(effect, 60)


def frame(effect: str, lines: list[str], tick: int,
          span: int | None = None) -> tuple[list[str], Heat]:
    """The drawing and its per-cell heat, 0 resting to 1 at full glow."""
    rows = _grid(lines)
    if not rows or not rows[0]:
        return list(lines), {}
    draw = _EFFECTS.get(effect, _ignite)
    rows, heat = draw(rows, max(tick, 0), max(span or effect_span(effect), 1))
    return ["".join(row).rstrip() for row in rows], heat


def _grid(lines: list[str]) -> list[list[str]]:
    width = max((len(line) for line in lines), default=0)
    return [list(line.ljust(width)) for line in lines]


def _noise(*seed: int) -> float:
    value = 2166136261
    for part in seed:
        value = ((value ^ (part & 0xFFFFFFFF)) * 16777619) & 0xFFFFFFFF
    return ((value >> 8) & 0xFFFF) / 65535.0


def _filled(rows: list[list[str]]):
    for row, line in enumerate(rows):
        for column, glyph in enumerate(line):
            if glyph != " ":
                yield row, column, glyph


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return low if value < low else high if value > high else value


def _ignite(rows, tick, span):
    height, width = len(rows), len(rows[0])
    reach = width + height * 2 + 16
    front = tick / span * reach
    heat: Heat = {}
    for row, column, _ in _filled(rows):
        behind = front - (column + row * 2)
        if behind < 0:
            level = 0.0
        elif behind < 4:
            level = 1.0
        else:
            ember = _noise(row, column, tick // 3) * 0.3
            level = _clamp(0.95 - (behind - 4) / 18 + ember, 0.3)
        heat[(row, column)] = level
    return rows, heat


def _ripple(rows, tick, span):
    height, width = len(rows), len(rows[0])
    middle, centre = (height - 1) / 2, (width - 1) / 2
    peak = math.hypot(centre * 0.5, middle) + 3
    lead = tick / span * peak * 2.1
    heat: Heat = {}
    for row, column, _ in _filled(rows):
        away = math.hypot((column - centre) * 0.5, row - middle)
        level = 0.0
        for ring in (lead, lead - peak * 0.6, lead - peak * 1.15):
            if ring < 0:
                continue
            gap = abs(away - ring)
            if gap < 2.4:
                level = max(level, (1 - gap / 2.4) ** 0.7)
        heat[(row, column)] = level * 0.8 + 0.2
    return rows, heat


def _glitch(rows, tick, span):
    height, width = len(rows), len(rows[0])
    window = tick // 3
    torn = window % 4 == 0 and tick < span - 6
    heat: Heat = {}
    if not torn:
        settle = _clamp(1 - (tick % 12) / 12, 0.25, 0.55)
        for row, column, _ in _filled(rows):
            heat[(row, column)] = settle
        return rows, heat
    out = [list(line) for line in rows]
    for row in range(height):
        shear = int(_noise(row, window, 5) * 9) - 4
        if abs(shear) < 2:
            for column, glyph in enumerate(rows[row]):
                if glyph != " ":
                    heat[(row, column)] = 0.4
            continue
        for column in range(width):
            source = (column - shear) % width
            glyph = rows[row][source]
            if glyph != " " and _noise(row, column, window, 9) > 0.82:
                glyph = GLITCH_GLYPHS[int(_noise(column, window) * len(GLITCH_GLYPHS))]
            out[row][column] = glyph
            if glyph != " ":
                heat[(row, column)] = 1.0 if abs(shear) > 2 else 0.7
    return out, heat


def _rain(rows, tick, span):
    height, width = len(rows), len(rows[0])
    out = [list(line) for line in rows]
    heat: Heat = {(row, column): 0.22 for row, column, _ in _filled(rows)}
    fade = _clamp(1 - (tick - span * 0.7) / (span * 0.3)) if tick > span * 0.7 else 1.0
    for column in range(width):
        seed = int(_noise(column, 3) * 1000)
        trail = 4 + seed % 5
        head = (tick * (2 + seed % 3)) // 3 - seed % 23
        for step in range(trail):
            row = head - step
            if not 0 <= row < height:
                continue
            level = (1 - step / trail) * fade
            if rows[row][column] == " ":
                if level > 0.25:
                    out[row][column] = RAIN_GLYPHS[(seed + row) % len(RAIN_GLYPHS)]
                    heat[(row, column)] = level * 0.8
            else:
                heat[(row, column)] = max(heat[(row, column)], level)
    return out, heat


def _assemble(rows, tick, span):
    height, width = len(rows), len(rows[0])
    out = [[" "] * width for _ in range(height)]
    heat: Heat = {}
    for row, column, glyph in _filled(rows):
        wait = column / max(width - 1, 1) * 0.3 + _noise(row, column, 1) * 0.18
        moment = _clamp((tick / span - wait) / max(1 - wait, 0.05))
        eased = 1 - (1 - moment) ** 3
        scattered_row = int(_noise(row, column, 2) * height)
        scattered_column = int(_noise(row, column, 3) * width)
        spot = _slot(out,
                     round(scattered_row + (row - scattered_row) * eased),
                     round(scattered_column + (column - scattered_column) * eased))
        if spot is None:
            continue
        out[spot[0]][spot[1]] = glyph
        heat[spot] = max(heat.get(spot, 0.0), _clamp(1 - eased * 0.8, 0.2))
    return out, heat


def _slot(out, row, column):
    """Nearest free cell, so glyphs still in flight never eat each other."""
    height, width = len(out), len(out[0])
    row = max(0, min(row, height - 1))
    column = max(0, min(column, width - 1))
    if out[row][column] == " ":
        return row, column
    for reach in range(1, height + width):
        for near_row in range(max(0, row - reach), min(height, row + reach + 1)):
            for near in (column - reach, column + reach):
                if 0 <= near < width and out[near_row][near] == " ":
                    return near_row, near
        for near_row in (row - reach, row + reach):
            if not 0 <= near_row < height:
                continue
            for near in range(max(0, column - reach), min(width, column + reach + 1)):
                if out[near_row][near] == " ":
                    return near_row, near
    return None


def _scan(rows, tick, span):
    height, width = len(rows), len(rows[0])
    bar = tick / span * (width + 8) - 4
    out = [list(line) for line in rows]
    heat: Heat = {}
    for row in range(height):
        for column in range(width):
            glyph = rows[row][column]
            ahead = column - bar
            if ahead > 1.5:
                if glyph != " " and _noise(row, column, tick // 2) > 0.35:
                    out[row][column] = NOISE_GLYPHS[
                        int(_noise(row, column, tick // 2, 7) * len(NOISE_GLYPHS))]
                if glyph != " ":
                    heat[(row, column)] = 0.1
            elif ahead > -1.5:
                if glyph == " ":
                    out[row][column] = SCAN_BAR
                heat[(row, column)] = 1.0
            elif glyph != " ":
                heat[(row, column)] = _clamp(0.75 + ahead / 10, 0.35, 0.75)
    return out, heat


_EFFECTS = {"ignite": _ignite, "ripple": _ripple, "glitch": _glitch,
            "rain": _rain, "assemble": _assemble, "scan": _scan}


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
