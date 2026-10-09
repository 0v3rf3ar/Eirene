"""Silent, unlisted snowfall toggle."""

from . import register


@register("snow", "", hidden=True)
async def run(app, args: str) -> None:
    if not args:
        app.transcript._snowfall.toggle()
