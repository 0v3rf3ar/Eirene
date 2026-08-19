"""Interactive application theme selection."""

from __future__ import annotations

from ..core.errors import CommandError
from ..ui import theme as themes
from . import register


DESCRIPTIONS = {
    "default": "Terminal-native colors with a transparent-compatible background.",
    "matrix": "Neon green text and electric green accents on pure black.",
    "hacker-red": "Neon red text and vivid crimson accents on near-black.",
    "gruvbox": "Cream text, green details, and orange accents on warm brown-black.",
    "catppuccin": "The Mocha palette with soft lavender, blue, green, and rose.",
    "dracula": "The classic purple, pink, cyan, and green dark palette.",
    "nord": "Cool arctic blues with restrained green and amber accents.",
    "tokyo-night": "Deep navy with luminous blue, violet, green, and gold.",
    "solarized-dark": "Low-contrast blue-black with Solarized blue and yellow.",
    "monokai": "Charcoal with vivid pink, green, yellow, and orange.",
    "one-dark": "Atom's balanced charcoal, blue, green, and amber palette.",
    "rose-pine": "Muted ink, foam blue, iris purple, rose, and gold.",
    "ayu-dark": "Near-black with warm gold, lime, cyan, and coral accents.",
    "everforest": "Soft forest greens with warm orange and aqua on slate.",
    "kanagawa": "Ink-wash palette with crystal blue, spring green, and sakura.",
    "night-owl": "Midnight navy with bright blue, lime, and teal for late work.",
    "solarized-light": "Solarized on warm paper: blue, green, and cyan on cream.",
    "gruvbox-light": "Gruvbox on light parchment with burnt orange and olive.",
    "latte": "Catppuccin Latte: mauve, green, and teal on a cool light page.",
}


@register("theme", "choose and apply an interface theme", "/theme [name]")
async def run(app, args: str) -> None:
    wanted = args.strip()
    if wanted:
        chosen = themes.resolve(wanted)
        if chosen is None:
            raise CommandError(f"unknown theme '{wanted}'")
    else:
        current = themes.resolve(str(app.config.get("theme", "default"))) or "default"
        options = [(key, themes.LABELS[key], "current" if key == current else "",
                    DESCRIPTIONS[key]) for key in themes.THEMES]
        chosen = await app.ask_choice(
            "interface themes", options,
            on_highlight=lambda key: setattr(app, "theme", themes.THEMES[key].name),
            selected=current)
        if not chosen:
            app.theme = themes.THEMES[current].name
            return

    app.theme = themes.THEMES[chosen].name
    app.config.set("theme", chosen)
    app._save_config()
    app.refresh(layout=True)
