"""/skills"""

from __future__ import annotations

from rich.text import Text

from ..core import paths
from ..ui import art
from ..ui.chat import Block
from . import register


@register("skills", "enable or disable the markdown skills")
async def run(app, args: str) -> None:
    found = app.agent.reload_skills()
    if not found:
        body = Text()
        body.append(f"{art.icon('skill')} no skills yet\n", style="bold")
        body.append(f"  drop .md files in {paths.skills_dir()}\n", style="dim")
        body.append("  each one is added to the prompt when enabled\n", style="dim")
        await app.push(Block(body))
        return

    while True:
        options = []
        for skill in found:
            mark = art.icon("ok") if skill.enabled else art.icon("fail")
            state = "on" if skill.enabled else "off"
            options.append((skill.name, f"{mark} {skill.title}",
                            f"{state} · ~{skill.tokens} tokens",
                            skill.description or "no description"))
        options.append(("", "done", "", "close this list"))
        chosen = await app.ask_choice("toggle a skill", options)
        if not chosen:
            break
        for skill in found:
            if skill.name == chosen:
                skill.enabled = not skill.enabled
                app.config.set_skill(skill.name, skill.enabled)
                app._save_config()
                app.say(f"{skill.title} {'enabled' if skill.enabled else 'disabled'}")
                break

    active = [s for s in found if s.enabled]
    total = sum(s.tokens for s in active)
    app.say(f"{len(active)} of {len(found)} skills on (~{total} tokens per request)")
