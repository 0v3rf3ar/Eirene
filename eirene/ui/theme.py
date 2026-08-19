"""Built-in application themes."""

from __future__ import annotations

from dataclasses import dataclass, replace

from textual.theme import Theme


def _plain_theme() -> Theme:
    """Terminal defaults only, no colour of our own."""
    from textual.theme import BUILTIN_THEMES

    variables = dict(BUILTIN_THEMES["ansi-dark"].variables)
    variables.update({
        "ansi-background": "ansi_default",
        "ansi-foreground": "ansi_default",
        "block-cursor-foreground": "ansi_default",
        "block-cursor-background": "ansi_default",
        "block-cursor-text-style": "reverse",
        "input-cursor-background": "ansi_default",
        "input-cursor-foreground": "ansi_default",
        "input-cursor-text-style": "reverse",
        "input-selection-background": "ansi_bright_black",
        "input-selection-foreground": "ansi_default",
        # Sent messages use bright black, so using it here makes a drag
        # selection completely invisible on the text users most often copy.
        "screen-selection-background": "ansi_bright_blue",
        "screen-selection-foreground": "ansi_black",
        "border-blurred": "ansi_default",
        "scrollbar": "ansi_bright_black",
        "scrollbar-background": "ansi_default",
        "scrollbar-hover": "ansi_bright_black",
        "scrollbar-active": "ansi_white",
        "footer-key-foreground": "ansi_default",
    })
    return Theme(name="eirene", primary="ansi_default", secondary="ansi_default",
                 accent="ansi_default", foreground="ansi_default",
                 background="ansi_default", success="ansi_default",
                 warning="ansi_default", error="ansi_default",
                 surface="ansi_default", panel="ansi_default",
                 boost="ansi_default", dark=True, ansi=True, variables=variables)


PLAIN = _plain_theme()


def _theme(name: str, foreground: str, background: str, accent: str,
           secondary: str, panel: str, error: str = "#ff5555",
           warning: str = "#f1fa8c", primary: str | None = None,
           dark: bool = True) -> Theme:
    return Theme(name=f"eirene-{name}", primary=primary or accent, secondary=secondary,
                 accent=accent, foreground=foreground, background=background,
                 success=secondary, warning=warning, error=error,
                 surface=background, panel=panel, boost=panel, dark=dark)


THEMES: dict[str, Theme] = {
    "default": PLAIN,
    "matrix": _theme("matrix", "#00ff41", "#000000", "#39ff14", "#00ff00",
                     "#062b0f"),
    "hacker-red": _theme("hacker-red", "#ff3131", "#050000", "#ff1744",
                         "#ff003c", "#2b0509", error="#ff0000"),
    "gruvbox": _theme("gruvbox", "#ebdbb2", "#282828", "#fe8019", "#b8bb26",
                      "#3c3836", error="#fb4934", warning="#fabd2f",
                      primary="#fabd2f"),
    "catppuccin": _theme("catppuccin", "#cdd6f4", "#1e1e2e", "#cba6f7",
                         "#a6e3a1", "#313244", error="#f38ba8", warning="#f9e2af"),
    "dracula": _theme("dracula", "#f8f8f2", "#282a36", "#bd93f9", "#50fa7b",
                      "#44475a", error="#ff5555", warning="#f1fa8c"),
    "nord": _theme("nord", "#d8dee9", "#2e3440", "#88c0d0", "#a3be8c",
                   "#3b4252", error="#bf616a", warning="#ebcb8b"),
    "tokyo-night": _theme("tokyo-night", "#c0caf5", "#1a1b26", "#7aa2f7",
                          "#9ece6a", "#24283b", error="#f7768e", warning="#e0af68"),
    "solarized-dark": _theme("solarized-dark", "#839496", "#002b36", "#268bd2",
                             "#859900", "#073642", error="#dc322f", warning="#b58900"),
    "monokai": _theme("monokai", "#f8f8f2", "#272822", "#f92672", "#a6e22e",
                      "#3e3d32", error="#f92672", warning="#e6db74"),
    "one-dark": _theme("one-dark", "#abb2bf", "#282c34", "#61afef", "#98c379",
                       "#353b45", error="#e06c75", warning="#e5c07b"),
    "rose-pine": _theme("rose-pine", "#e0def4", "#191724", "#c4a7e7", "#9ccfd8",
                        "#26233a", error="#eb6f92", warning="#f6c177"),
    "ayu-dark": _theme("ayu-dark", "#bfbdb6", "#0b0e14", "#e6b450", "#aad94c",
                       "#1f2430", error="#f07178", warning="#ffb454"),
    "everforest": _theme("everforest", "#d3c6aa", "#2d353b", "#e69875", "#a7c080",
                         "#343f44", error="#e67e80", warning="#dbbc7f"),
    "kanagawa": _theme("kanagawa", "#dcd7ba", "#1f1f28", "#7e9cd8", "#98bb6c",
                       "#2a2a37", error="#e46876", warning="#dca561"),
    "night-owl": _theme("night-owl", "#d6deeb", "#011627", "#82aaff", "#addb67",
                        "#0b2942", error="#ef5350", warning="#ecc48d"),
    "solarized-light": _theme("solarized-light", "#657b83", "#fdf6e3", "#268bd2",
                              "#859900", "#eee8d5", error="#dc322f",
                              warning="#b58900", dark=False),
    "gruvbox-light": _theme("gruvbox-light", "#3c3836", "#fbf1c7", "#af3a03",
                            "#79740e", "#ebdbb2", error="#9d0006",
                            warning="#b57614", dark=False),
    "latte": _theme("latte", "#4c4f69", "#eff1f5", "#8839ef", "#40a02b",
                    "#ccd0da", error="#d20f39", warning="#df8e1d", dark=False),
}

LABELS = {
    "default": "Default", "matrix": "Matrix", "hacker-red": "Hacker Red",
    "gruvbox": "Gruvbox", "catppuccin": "Catppuccin Mocha", "dracula": "Dracula",
    "nord": "Nord", "tokyo-night": "Tokyo Night", "solarized-dark": "Solarized Dark",
    "monokai": "Monokai", "one-dark": "One Dark", "rose-pine": "Rosé Pine",
    "ayu-dark": "Ayu Dark", "everforest": "Everforest", "kanagawa": "Kanagawa",
    "night-owl": "Night Owl", "solarized-light": "Solarized Light",
    "gruvbox-light": "Gruvbox Light", "latte": "Catppuccin Latte",
}


def resolve(name: str) -> str | None:
    """Return a canonical theme key from a user-facing name."""
    wanted = name.strip().lower().replace("_", "-").replace(" ", "-")
    if wanted in THEMES:
        return wanted
    matches = [key for key in THEMES if key.startswith(wanted)]
    return matches[0] if len(matches) == 1 else None


@dataclass(frozen=True)
class Accents:
    """The extra colours a theme paints its separate sections with."""

    rule: str
    marker: str
    code: str
    sent: str = ""
    tool: str = ""
    thinking: str = ""
    art: str = ""
    detail: str = ""
    glow: str = ""
    spark: str = ""
    surface: str = ""
    on_surface: str = ""


ACCENTS: dict[str, Accents] = {
    # Three voices each: a headline colour, a quiet body, and a frame. Tools,
    # reasoning and the banner animation borrow from the same family.
    "gruvbox": Accents(rule="#98971a", marker="#fe8019",
                       code="#b8bb26 on #3c3836", sent="#fe8019",
                       tool="#8ec07c", thinking="#928374",
                       art="#fe8019", detail="#bdae93",
                       glow="#fabd2f", spark="#d65d0e"),
    "catppuccin": Accents(rule="#a6e3a1", marker="#cba6f7",
                          code="#a6e3a1 on #313244", sent="#cba6f7",
                          tool="#94e2d5", thinking="#6c7086",
                          art="#cba6f7", detail="#a6adc8",
                          glow="#f9e2af", spark="#f5c2e7"),
    "tokyo-night": Accents(rule="#bb9af7", marker="#7aa2f7",
                           code="#9ece6a on #24283b", sent="#7aa2f7",
                           tool="#7dcfff", thinking="#565f89",
                           art="#7aa2f7", detail="#a9b1d6",
                           glow="#e0af68", spark="#f7768e"),
    "dracula": Accents(rule="#50fa7b", marker="#bd93f9",
                       code="#50fa7b on #44475a", sent="#bd93f9",
                       tool="#8be9fd", thinking="#6272a4",
                       art="#bd93f9", detail="#bfc0d0",
                       glow="#f1fa8c", spark="#ff79c6"),
    "nord": Accents(rule="#a3be8c", marker="#88c0d0",
                    code="#a3be8c on #3b4252", sent="#88c0d0",
                    tool="#8fbcbb", thinking="#616e88",
                    art="#88c0d0", detail="#aeb8c8",
                    glow="#ebcb8b", spark="#b48ead"),
    "solarized-dark": Accents(rule="#859900", marker="#268bd2",
                              code="#859900 on #073642", sent="#268bd2",
                              tool="#2aa198", thinking="#586e75",
                              art="#268bd2", detail="#93a1a1",
                              glow="#b58900", spark="#d33682"),
    "monokai": Accents(rule="#a6e22e", marker="#f92672",
                       code="#a6e22e on #3e3d32", sent="#f92672",
                       tool="#66d9ef", thinking="#75715e",
                       art="#f92672", detail="#cfcfc2",
                       glow="#e6db74", spark="#ae81ff"),
    "one-dark": Accents(rule="#98c379", marker="#61afef",
                        code="#98c379 on #353b45", sent="#61afef",
                        tool="#56b6c2", thinking="#5c6370",
                        art="#61afef", detail="#9aa2b1",
                        glow="#e5c07b", spark="#c678dd"),
    "rose-pine": Accents(rule="#9ccfd8", marker="#c4a7e7",
                         code="#9ccfd8 on #26233a", sent="#c4a7e7",
                         tool="#ebbcba", thinking="#6e6a86",
                         art="#c4a7e7", detail="#908caa",
                         glow="#f6c177", spark="#eb6f92"),
    "ayu-dark": Accents(rule="#aad94c", marker="#e6b450",
                        code="#aad94c on #1f2430", sent="#e6b450",
                        tool="#59c2ff", thinking="#626a73",
                        art="#e6b450", detail="#9a9891",
                        glow="#ffb454", spark="#d2a6ff"),
    "everforest": Accents(rule="#a7c080", marker="#e69875",
                          code="#a7c080 on #343f44", sent="#e69875",
                          tool="#83c092", thinking="#859289",
                          art="#e69875", detail="#9da9a0",
                          glow="#dbbc7f", spark="#d699b6"),
    "kanagawa": Accents(rule="#98bb6c", marker="#7e9cd8",
                        code="#98bb6c on #2a2a37", sent="#7e9cd8",
                        tool="#7aa89f", thinking="#727169",
                        art="#7e9cd8", detail="#a9a48f",
                        glow="#e6c384", spark="#d27e99"),
    "night-owl": Accents(rule="#addb67", marker="#82aaff",
                         code="#addb67 on #0b2942", sent="#82aaff",
                         tool="#7fdbca", thinking="#637777",
                         art="#82aaff", detail="#a7b6cc",
                         glow="#ecc48d", spark="#c792ea"),
    # Light themes: the accents are the dark end of each palette.
    "solarized-light": Accents(rule="#859900", marker="#268bd2",
                               code="#859900 on #eee8d5", sent="#268bd2",
                               tool="#2aa198", thinking="#93a1a1",
                               art="#268bd2", detail="#657b83",
                               glow="#b58900", spark="#d33682"),
    "gruvbox-light": Accents(rule="#79740e", marker="#af3a03",
                             code="#79740e on #ebdbb2", sent="#af3a03",
                             tool="#427b58", thinking="#7c6f64",
                             art="#af3a03", detail="#665c54",
                             glow="#b57614", spark="#8f3f71"),
    "latte": Accents(rule="#40a02b", marker="#8839ef",
                     code="#40a02b on #ccd0da", sent="#8839ef",
                     tool="#179299", thinking="#9ca0b0",
                     art="#8839ef", detail="#6c6f85",
                     glow="#e64553", spark="#fe640b"),
}

def _with_surfaces(key: str, accent: Accents) -> Accents:
    """Rows and chips sit on the theme's own panel, not a fixed dark grey."""
    built = THEMES[key]
    return replace(accent, surface=accent.surface or built.panel,
                   on_surface=accent.on_surface or built.foreground)


ACCENTS = {key: _with_surfaces(key, value) for key, value in ACCENTS.items()}

_BY_THEME_NAME = {THEMES[key].name: value for key, value in ACCENTS.items()}


def accents(theme_name: str) -> Accents | None:
    """The extra colours of a theme, or None when it only has two."""
    return _BY_THEME_NAME.get(theme_name or "")


def for_widget(widget) -> Accents | None:
    """The current accents, or None for a widget built outside a running app."""
    try:
        return accents(widget.app.theme)
    except (RuntimeError, AttributeError):  # no active app, as in unit tests
        return None
