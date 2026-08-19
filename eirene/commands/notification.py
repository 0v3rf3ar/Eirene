"""/notification"""

from __future__ import annotations

from ..core import notify
from ..core.errors import CommandError
from ..ui import art
from . import register

ON = ("on", "enable", "enabled", "yes", "true", "1")
OFF = ("off", "disable", "disabled", "no", "false", "0")


@register("notification", "turn desktop notifications on or off",
          "/notification [on|off]")
async def run(app, args: str) -> None:
    want = args.strip().lower()
    current = bool(app.config.get("notifications", False))

    if not want:
        want = "off" if current else "on"
    if want in ON:
        state = True
    elif want in OFF:
        state = False
    elif want == "test":
        _test(app)
        return
    else:
        raise CommandError("say /notification on, off or test")

    if state and not notify.available():
        raise CommandError(f"no notification tool here - {_missing()}")

    app.config.set("notifications", state)
    app._save_config()
    word = "on" if state else "off"
    app.say(f"{art.icon('ok')} notifications {word}")
    if state:
        notify.send("Eirene", "notifications are on")


def _test(app) -> None:
    if not notify.available():
        raise CommandError(f"no notification tool here - {_missing()}")
    if notify.send("Eirene", "this is what a notification looks like"):
        app.say(f"{art.icon('ok')} sent one")
        return
    app.say("could not send it", "warn")


def _missing() -> str:
    if notify.IS_MAC:
        return "osascript is missing"
    if notify.IS_WINDOWS:
        return "powershell is missing"
    return "install libnotify for notify-send"
