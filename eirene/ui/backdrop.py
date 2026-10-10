"""Shared faint logo background for the trust screen and conversation."""

from functools import lru_cache

from textual import events
from textual.widgets import Static
from textual.color import Color
from rich.style import Style
from rich.text import Text

from .splash import pixel_logo


@lru_cache(maxsize=16)
def faded_pixel_logo(width: int, height: int, background: Color) -> Text:
    """Blend the face into the current terminal theme at 12% opacity."""
    picture = pixel_logo(width, height)
    faded = Text(picture.plain, no_wrap=True, overflow="crop")
    glyphs = list(picture.plain)
    ink = Color.parse("#000000" if background.brightness > 0.5 else "#ffffff")
    for span in picture.spans:
        style = span.style
        if not isinstance(style, Style):
            continue
        # The bundled grid was composited onto black. Treat its brightness as
        # coverage so empty pixels remain exactly the theme's background.
        top = Color.parse(style.color.name).brightness
        bottom = Color.parse(style.bgcolor.name).brightness
        foreground = background.blend(ink, top * 0.12)
        backdrop = background.blend(ink, bottom * 0.12)
        if top == 0:
            # Default ANSI foreground and background differ. Use spaces or a
            # lower half block to leave the empty top on the true background.
            glyphs[span.start] = "▄" if bottom else " "
            faded.stylize(Style(color=backdrop.rich_color if bottom else None,
                                bgcolor=background.rich_color), span.start, span.end)
        else:
            faded.stylize(Style(color=foreground.rich_color,
                                bgcolor=backdrop.rich_color), span.start, span.end)
    faded.plain = "".join(glyphs)
    return faded


class LogoBackdrop(Static):
    """Center Eirene's bundled face without taking space in the layout."""

    DEFAULT_CSS = """
    LogoBackdrop {
        layer: watermark;
        position: absolute;
        width: 100%;
        height: 100%;
        content-align: center middle;
        background: transparent;
        opacity: 12%;
    }
    """
    can_focus = False

    def on_resize(self, event: events.Resize) -> None:
        self.update(pixel_logo(max(1, event.size.width - 4),
                               max(1, event.size.height - 2)))
