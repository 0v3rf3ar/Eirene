"""Desktop notifications."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "Eirene"
ICON_NAME = "Eirene.png"
IS_WINDOWS = os.name == "nt"
IS_MAC = sys.platform == "darwin"


def icon_path() -> str:
    """The bundled logo, frozen or not."""
    if getattr(sys, "frozen", False):
        found = Path(getattr(sys, "_MEIPASS", ".")) / "img" / ICON_NAME
    else:
        found = Path(__file__).resolve().parents[2] / "img" / ICON_NAME
    return str(found) if found.exists() else ""


# Linux notifiers, best first: freedesktop, KDE, GNOME/XFCE, then dbus directly.
LINUX_TOOLS = ("notify-send", "kdialog", "zenity", "gdbus", "dbus-send",
               "termux-notification", "notify-send.py")


def linux_tool() -> str:
    """The first notifier installed here."""
    for name in LINUX_TOOLS:
        if shutil.which(name):
            return name
    return ""


def available() -> bool:
    """True when this machine can show one."""
    if IS_MAC:
        return bool(shutil.which("terminal-notifier") or shutil.which("osascript"))
    if IS_WINDOWS:
        return bool(shutil.which("powershell") or shutil.which("pwsh"))
    return bool(linux_tool())


def _command(title: str, body: str) -> list[str]:
    if IS_MAC:
        return _mac(title, body)
    if IS_WINDOWS:
        shell = "pwsh" if shutil.which("pwsh") else "powershell"
        return [shell, "-NoProfile", "-Command", _toast(title, body)]
    return _linux(linux_tool(), title, body)


def _mac(title: str, body: str) -> list[str]:
    if shutil.which("terminal-notifier"):
        command = ["terminal-notifier", "-title", APP_NAME, "-subtitle", title,
                   "-message", body or " "]
        icon = icon_path()
        if icon:
            command += ["-appIcon", icon]
        return command
    script = (f'display notification {_quote(body)} '
              f'with title {_quote(APP_NAME)} subtitle {_quote(title)}')
    return ["osascript", "-e", script]


def _linux(tool: str, title: str, body: str) -> list[str]:
    """One notification, whichever tool this desktop has."""
    icon = icon_path()
    if tool in ("notify-send", "notify-send.py"):
        command = [tool, "-a", APP_NAME]
        if icon:
            command += ["-i", icon]
        return command + [title, body]
    if tool == "kdialog":
        command = ["kdialog", "--title", APP_NAME]
        if icon:
            command += ["--icon", icon]
        return command + ["--passivepopup", f"{title}\n{body}".strip(), "6"]
    if tool == "zenity":
        return ["zenity", "--notification",
                f"--text={APP_NAME}: {title}\n{body}".rstrip()]
    if tool == "termux-notification":
        return ["termux-notification", "--title", f"{APP_NAME}: {title}",
                "--content", body]
    if tool == "gdbus":
        return ["gdbus", "call", "--session",
                "--dest", "org.freedesktop.Notifications",
                "--object-path", "/org/freedesktop/Notifications",
                "--method", "org.freedesktop.Notifications.Notify",
                APP_NAME, "0", icon or "dialog-information", title, body,
                "[]", "{}", "6000"]
    return ["dbus-send", "--session", "--type=method_call",
            "--dest=org.freedesktop.Notifications",
            "/org/freedesktop/Notifications",
            "org.freedesktop.Notifications.Notify",
            f"string:{APP_NAME}", "uint32:0",
            f"string:{icon or 'dialog-information'}",
            f"string:{title}", f"string:{body}",
            "array:string:", "dict:string:variant:", "int32:6000"]


def _quote(text: str) -> str:
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _toast(title: str, body: str) -> str:
    """A balloon tip, using only what ships with Windows."""
    safe_title = str(title).replace("'", "''")
    safe_body = str(body).replace("'", "''")
    return (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$n = New-Object System.Windows.Forms.NotifyIcon;"
        "$n.Icon = [System.Drawing.SystemIcons]::Information;"
        "$n.Visible = $true;"
        f"$n.BalloonTipTitle = '{safe_title}';"
        f"$n.BalloonTipText = '{safe_body}';"
        "$n.ShowBalloonTip(5000);"
        "Start-Sleep -Seconds 6;"
        "$n.Dispose()"
    )


def send(title: str, body: str = "") -> bool:
    """Show one notification; never raises."""
    if not available():
        return False
    try:
        subprocess.Popen(_command(title, body), stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    except (OSError, ValueError):
        return False
    return True
