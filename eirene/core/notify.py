"""Desktop notifications."""

from __future__ import annotations

from .subprocesses import external_environment

import atexit
import base64
import functools
import os
import shutil
import subprocess
import sys
import threading
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


MAC_TERMINALS = {"Apple_Terminal": "com.apple.Terminal", "iTerm.app": "com.googlecode.iterm2"}

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
                   "-message", body or " ", "-group", f"eirene-{os.getpid()}"]
        terminal = mac_terminal()
        if terminal:
            command += ["-activate", terminal]
        icon = icon_path()
        if icon:
            command += ["-appIcon", icon]
        return command
    script = (f'display notification {_quote(body)} '
              f'with title {_quote(APP_NAME)} subtitle {_quote(title)}')
    return ["osascript", "-e", script]


def mac_terminal() -> str:
    """The bundle id of the terminal app Eirene runs in."""
    return (os.environ.get("__CFBundleIdentifier")
            or MAC_TERMINALS.get(os.environ.get("TERM_PROGRAM", ""), ""))


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


# Windows PowerShell 5.1 ships with Windows and can load the WinRT toast API.
WINDOWS_TOAST = r"""
$ErrorActionPreference = 'Stop'
$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
function Safe($text) { [Security.SecurityElement]::Escape([string]$text) }
$logo = ''
if ($env:EIRENE_TOAST_ICON) { $logo = "<image placement='appLogoOverride' src='$(Safe (([Uri]$env:EIRENE_TOAST_ICON).AbsoluteUri))'/>" }
$xml = [Windows.Data.Xml.Dom.XmlDocument]::new()
$xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$(Safe $env:EIRENE_TOAST_TITLE)</text><text>$(Safe $env:EIRENE_TOAST_BODY)</text>$logo<text placement='attribution'>Eirene</text></binding></visual></toast>")
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$toast.Tag = 'eirene'
$toast.Group = $env:EIRENE_TOAST_GROUP
$null = Register-ObjectEvent -InputObject $toast -EventName Activated -SourceIdentifier clicked
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe').Show($toast)
$null = Wait-Event -SourceIdentifier clicked
Add-Type -Namespace Eirene -Name Window -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr window);
[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr window, int command);
[DllImport("user32.dll")] public static extern bool IsIconic(IntPtr window);
[DllImport("user32.dll")] public static extern void keybd_event(byte key, byte scan, uint flags, UIntPtr extra);
'@
# Walk up from Eirene to the first process that owns a window: the terminal.
$id = [int]$env:EIRENE_TOAST_PID
for ($i = 0; $i -lt 10 -and $id; $i++) {
    $process = Get-Process -Id $id -ErrorAction SilentlyContinue
    if ($process -and $process.MainWindowHandle -ne [IntPtr]::Zero) {
        $window = $process.MainWindowHandle
        if ([Eirene.Window]::IsIconic($window)) { $null = [Eirene.Window]::ShowWindow($window, 9) }
        # Windows only lets the active app take focus; a synthetic Alt press lifts that lock.
        [Eirene.Window]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero)
        [Eirene.Window]::keybd_event(0x12, 0, 2, [UIntPtr]::Zero)
        $null = [Eirene.Window]::SetForegroundWindow($window)
        break
    }
    $id = (Get-CimInstance Win32_Process -Filter "ProcessId=$id").ParentProcessId
}
"""


def send(title: str, body: str = "") -> bool:
    """Show one notification; never raises."""
    if not available():
        return False
    if _replaceable() or (IS_WINDOWS and shutil.which("powershell")):
        global _sender
        target = _send_windows if IS_WINDOWS else _send_replacing
        _sender = threading.Thread(target=target, args=(title, body), daemon=True)
        _sender.start()
        return True
    try:
        subprocess.Popen(_command(title, body), stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, env=external_environment())
    except (OSError, ValueError):
        return False
    return True


# GTK terminals that can be raised over D-Bus, by the variable they set.
TERMINAL_APPS = (
    ("PTYXIS_VERSION", ("app.devsuite.Ptyxis", "org.gnome.Ptyxis", "org.gnome.Ptyxis.Devel")),
    ("GNOME_TERMINAL_SCREEN", ("org.gnome.Terminal",)),
    ("TILIX_ID", ("com.gexperts.Tilix",)),
    ("GHOSTTY_RESOURCES_DIR", ("com.mitchellh.ghostty",)),
)

_lock = threading.Lock()
_sender: threading.Thread | None = None
_waiter: subprocess.Popen | None = None
_last_id = 0


@functools.cache
def _replaceable() -> bool:
    """notify-send 0.8+ can replace, wait for a click and pass the focus token."""
    if IS_MAC or IS_WINDOWS or not shutil.which("notify-send"):
        return False
    try:
        usage = subprocess.run(["notify-send", "--help"], capture_output=True, text=True,
                               timeout=5, env=external_environment()).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "--replace-id" in usage and "--activation-token-fd" in usage


def _send_replacing(title: str, body: str) -> None:
    """Keep one notification per session and raise the terminal when it is clicked."""
    global _waiter, _last_id
    with _lock:
        # GNOME refuses to replace a notification while another client still waits on it.
        _stop_waiter()
        for replace in ([_last_id] if _last_id else []) + [0]:
            read, write = os.pipe()
            argv = ["notify-send", "-a", APP_NAME, "-p", "-A", "default=Open",
                    f"--activation-token-fd={write}"]
            if icon_path():
                argv += ["-i", icon_path()]
            if replace:
                argv += ["-r", str(replace)]
            try:
                process = subprocess.Popen(argv + [title, body], stdout=subprocess.PIPE,
                                           stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                           pass_fds=(write,), text=True, env=external_environment())
            except OSError:
                os.close(read)
                return
            finally:
                os.close(write)
            shown = process.stdout.readline().strip()
            if shown.isdigit():
                _last_id, _waiter = int(shown), process
                threading.Thread(target=_wait_for_click, args=(process, read), daemon=True).start()
                return
            # The old notification was dismissed; show a fresh one.
            process.kill()
            process.wait()
            os.close(read)


def _send_windows(title: str, body: str) -> None:
    """A toast that replaces this session's last one and raises the terminal on click."""
    global _waiter
    with _lock:
        _stop_waiter()
        env = external_environment()
        env.update(EIRENE_TOAST_TITLE=title, EIRENE_TOAST_BODY=body, EIRENE_TOAST_ICON=icon_path(),
                   EIRENE_TOAST_GROUP=f"eirene-{os.getpid()}", EIRENE_TOAST_PID=str(os.getpid()))
        script = base64.b64encode(WINDOWS_TOAST.encode("utf-16-le")).decode("ascii")
        try:
            _waiter = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", script],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError:
            pass


def _stop_waiter() -> None:
    if _waiter is not None and _waiter.poll() is None:
        _waiter.terminate()
        _waiter.wait()


def _wait_for_click(process: subprocess.Popen, read: int) -> None:
    action = process.stdout.readline().strip()
    with os.fdopen(read) as tokens:
        token = tokens.read().strip()
    if action == "default":
        _raise_terminal(token)


def _raise_terminal(token: str) -> None:
    """Bring the terminal window forward; Wayland only allows it with the click's token."""
    app = _terminal_app()
    if app:
        value = "'" + token.replace("\\", "\\\\").replace("'", "\\'") + "'"
        data = (f"{{'activation-token': <{value}>, 'desktop-startup-id': <{value}>}}"
                if token else "@a{sv} {}")
        _quiet(["gdbus", "call", "--session", "--dest", app,
                "--object-path", "/" + app.replace(".", "/").replace("-", "_"),
                "--method", "org.freedesktop.Application.Activate", data])
    elif os.environ.get("WINDOWID") and shutil.which("xdotool"):
        _quiet(["xdotool", "windowactivate", os.environ["WINDOWID"]])


def _terminal_app() -> str:
    if not shutil.which("gdbus"):
        return ""
    for marker, apps in TERMINAL_APPS:
        if not os.environ.get(marker):
            continue
        for app in apps:
            owned = _quiet(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
                            "--object-path", "/org/freedesktop/DBus",
                            "--method", "org.freedesktop.DBus.NameHasOwner", f"'{app}'"])
            if "true" in owned:
                return app
    return ""


def _quiet(argv: list[str]) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=5,
                              env=external_environment()).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


@atexit.register
def _shutdown() -> None:
    if _sender is not None:
        _sender.join(5)
    if _waiter is not None and _waiter.poll() is None:
        _waiter.terminate()
