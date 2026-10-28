"""/skills"""

from __future__ import annotations

from rich.text import Text

from ..core import paths
from ..ui import art
from ..ui.chat import Block
from . import register


@register("skills", "enable or disable the markdown skills, alone or by folder")
async def run(app, args: str) -> None:
    found = app.agent.reload_skills()
    if not found:
        body = Text()
        body.append(f"{art.icon('skill')} no skills yet\n", style="bold")
        body.append(f"  drop .md files in {paths.skills_dir()}\n", style="dim")
        body.append("  each one is added to the prompt when enabled\n", style="dim")
        await app.push(Block(body))
        return

    selected = ""
    while True:
        found = app.agent.reload_skills()
        groups: dict[str, list] = {}
        for skill in found:
            if skill.group:
                groups.setdefault(skill.group, []).append(skill)
        options = []
        for name, members in sorted(groups.items()):
            enabled = sum(skill.enabled for skill in members)
            options.append(("group:" + name, f"{art.icon('dir')} {name}",
                            f"{enabled}/{len(members)} enabled", _group_detail(app, name)))
        options += [_skill_row(skill) for skill in found if not skill.group]
        chosen = await app.ask_choice("skills — toggle one, or open a folder", options,
                                      selected=selected, right_hint=True)
        if not chosen:
            break
        selected = chosen
        kind, _, name = chosen.partition(":")
        if kind == "group":
            await _manage_group(app, name)
        else:
            _toggle(app, name)


async def _manage_group(app, group: str) -> None:
    """Enable or disable a folder at once, or pick its skills one by one."""
    selected = ""
    while True:
        members = [skill for skill in app.agent.reload_skills() if skill.group == group]
        if not members:
            return
        enabled = sum(skill.enabled for skill in members)
        detail = _group_detail(app, group)
        options = [("all:on", f"{art.icon('ok')} Enable all", f"{len(members)} skills", detail),
                   ("all:off", f"{art.icon('fail')} Disable all", f"{len(members)} skills", detail)]
        options += [_skill_row(skill) for skill in members]
        chosen = await app.ask_choice(f"{group} — {enabled}/{len(members)} enabled", options,
                                      selected=selected, right_hint=True)
        if not chosen:
            return
        selected = chosen
        kind, _, value = chosen.partition(":")
        if kind == "all":
            for skill in members:
                app.config.set_skill(skill.name, value == "on")
            app._save_config()
        else:
            _toggle(app, value)


def _skill_row(skill) -> tuple:
    mark = art.icon("ok") if skill.enabled else art.icon("fail")
    return ("skill:" + skill.name, f"{mark} {skill.title}", f"~{skill.tokens} tokens",
            skill.description or "no description")


def _group_detail(app, group: str) -> str:
    from ..core import plugins
    folder = paths.skills_dir() / group
    if any(p.name == group for p in plugins.discover()) and not app.config.plugin_enabled(group):
        return f"{folder} · plugin disabled; enable it with /plugins first"
    return str(folder)


def _toggle(app, name: str) -> None:
    app.config.set_skill(name, not app.config.skill_enabled(name, True))
    app._save_config()
