"""/help"""

from __future__ import annotations

from rich.text import Text

from ..ui import art
from . import REGISTRY, commands, register
from ..ui.shortcuts import SHORTCUTS, EDITING_KEYS

# Names only, grouped by topic; options appear in the / menu as you type.
GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Conversation", ("btw", "clear", "compact", "plan", "review", "sessions",
                      "subagents", "usage")),
    ("Model & provider", ("connect", "model", "fast", "think", "prompt-suggest", "recap")),
    ("Modes & access", ("agents", "permissions", "sandbox")),
    ("Tools & extensions", ("mcp", "plugins", "skills", "search-api", "schedule", "tasks")),
    ("Interface", ("theme", "diff", "companion", "notification", "keybindings", "config")),
    ("Eirene", ("pwd", "update", "restart", "help", "exit")),
)

# One short line each, so the description sits beside its command.
SHORT = {
    "agents": "change mode or list specialists",
    "btw": "ask a side question",
    "clear": "wipe the session",
    "compact": "summarise the chat",
    "companion": "toggle the companion",
    "config": "open the config file",
    "connect": "sign in or switch provider",
    "diff": "toggle the Git changes panel",
    "exit": "leave Eirene",
    "fast": "faster output, higher price",
    "help": "this menu",
    "keybindings": "show keyboard shortcuts",
    "mcp": "manage MCP servers",
    "model": "pick a model",
    "notification": "desktop notifications on/off",
    "permissions": "sandboxed or full access",
    "plan": "show or clear the plan",
    "plugins": "manage plugins",
    "prompt-suggest": "follow-up suggestions on/off",
    "pwd": "show the working directory",
    "recap": "session recaps on/off",
    "restart": "restart, keeping this chat",
    "review": "review uncommitted changes",
    "sandbox": "show sandbox status",
    "schedule": "schedule a task",
    "search-api": "configure web search",
    "sessions": "switch, search, export",
    "skills": "enable or disable skills",
    "subagents": "browse subagent sessions",
    "tasks": "list scheduled tasks",
    "theme": "choose a theme",
    "think": "local thinking on/off",
    "update": "install the latest release",
    "usage": "tokens used this session",
}
SUMMARY_LIMIT = 40
# One column for every section, sized for built-in names; a longer label
# (a plugin command, a long key chord) keeps a two-space gap instead.
COLUMN = max(len(f"/{name}") for _, names in GROUPS for name in names) + 3


def _short(command) -> str:
    text = SHORT.get(command.name) or command.summary
    return text if len(text) <= SUMMARY_LIMIT else text[:SUMMARY_LIMIT - 1].rstrip() + "…"


def _section(body: Text, title: str, rows: list[tuple[str, str]]) -> None:
    if not rows:
        return
    body.append(f"\n {title}\n", style="bold")
    for left, right in rows:
        body.append(f"  {left:<{COLUMN}}" if len(left) < COLUMN - 1 else f"  {left}  ",
                    style="bold")
        body.append(f"{right}\n", style="dim")


def build(available) -> Text:
    by_name = {command.name: command for command in available}
    placed: set[str] = set()
    sections: list[tuple[str, list]] = []
    for title, names in GROUPS:
        found = [by_name[name] for name in names if name in by_name]
        placed.update(command.name for command in found)
        sections.append((title, found))
    rest = [command for command in available if command.name not in placed]
    # Plugin commands are added beside the built-in registry, never inside it.
    plugins = [command for command in rest if REGISTRY.get(command.name) is not command]
    sections.append(("Plugins", plugins))
    sections.append(("Other", [command for command in rest if command not in plugins]))

    body = Text()
    body.append(f"{art.icon('info')} Help\n", style="bold")
    for title, found in sections:
        _section(body, title, [(f"/{command.name}", _short(command)) for command in found])
    keys = [(label, hint) for _, _, label, hint in SHORTCUTS] + list(EDITING_KEYS)
    _section(body, "Keys", keys)
    body.append("\n Tips\n", style="bold")
    for tip in ("Type / to filter commands; Tab fills one in with its options.",
                "Click command output to expand it.",
                "Send a follow-up while working to queue it."):
        body.append(f"  {tip}\n", style="dim")
    return body


@register("help", "show this menu")
async def run(app, args: str) -> None:
    app.aside.show_content(build(commands(app)))
