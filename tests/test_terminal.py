"""Clipboard, terminal title and desktop notifications."""

from __future__ import annotations

import io
import os
import subprocess
from types import SimpleNamespace

import pytest

from eirene.core import notify
from eirene.ui import terminal


class Driver:
    """Records what would go to the terminal."""

    def __init__(self):
        self.written = []
        self.flushed = 0

    def write(self, text):
        self.written.append(text)

    def flush(self):
        self.flushed += 1


def test_the_title_is_an_osc_sequence():
    driver = Driver()
    assert terminal.write_terminal_title(driver, "eirene - my chat") is True
    assert driver.written == ["\x1b]0;eirene - my chat\x07"]
    assert driver.flushed == 1


def test_a_title_cannot_escape():
    driver = Driver()
    terminal.write_terminal_title(driver, "bad\x1b]0;evil\x07title\n")
    assert "\x1b" not in driver.written[0][5:]
    assert "evil" in driver.written[0]
    assert "\n" not in driver.written[0]


def test_a_very_long_title_is_cut():
    driver = Driver()
    terminal.write_terminal_title(driver, "x" * 400)
    assert len(driver.written[0]) < 200


def test_no_driver_is_not_a_crash():
    assert terminal.write_terminal_title(None, "anything") is False


def test_osc52_carries_the_text():
    import base64
    sequence = terminal.osc52("hello")
    assert sequence.startswith("\x1b]52;c;")
    payload = sequence[len("\x1b]52;c;"):-1]
    assert base64.b64decode(payload).decode() == "hello"


def test_osc52_reaches_the_terminal_through_multiplexers():
    plain = terminal.osc52("hi", {})
    tmux = terminal.osc52("hi", {"TMUX": "/tmp/tmux-1/default,1,0"})
    # Plain for `set-clipboard on`, and wrapped for `allow-passthrough on`.
    assert tmux.startswith(plain) and "\x1bPtmux;\x1b\x1b]52;c;" in tmux and tmux.endswith("\x1b\\")
    assert terminal.osc52("hi", {"STY": "1.pts"}) == "\x1bP" + plain + "\x1b\\"


def test_over_ssh_the_servers_clipboard_tools_are_never_used(monkeypatch):
    monkeypatch.setenv("SSH_CONNECTION", "10.0.0.2 51000 10.0.0.1 22")
    monkeypatch.setattr(terminal.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(terminal.subprocess, "run", lambda *a, **k: pytest.fail("ran a server clipboard tool"))
    assert terminal.remote_session() and terminal.copy_to_system("x") == ""


def test_the_clipboard_uses_a_real_helper(monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["input"] = kwargs.get("input")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(terminal.shutil, "which",
                        lambda name: "/usr/bin/wl-copy" if name == "wl-copy" else None)
    monkeypatch.setattr(terminal.subprocess, "run", fake_run)
    assert terminal.copy_to_system("copy me") == "wl-copy"
    assert seen["command"] == ["wl-copy"]
    assert seen["input"] == b"copy me"


def test_the_clipboard_falls_through_the_list(monkeypatch):
    monkeypatch.setattr(terminal.shutil, "which",
                        lambda name: "/usr/bin/xclip" if name == "xclip" else None)
    monkeypatch.setattr(terminal.subprocess, "run",
                        lambda command, **kw: subprocess.CompletedProcess(command, 0))
    assert terminal.copy_to_system("x") == "xclip"


def test_no_clipboard_helper_is_reported(monkeypatch):
    monkeypatch.setattr(terminal.shutil, "which", lambda name: None)
    assert terminal.copy_to_system("x") == ""


def test_a_failing_helper_is_reported(monkeypatch):
    monkeypatch.setattr(terminal.shutil, "which", lambda name: "/usr/bin/wl-copy")
    monkeypatch.setattr(terminal.subprocess, "run",
                        lambda command, **kw: subprocess.CompletedProcess(command, 1))
    assert terminal.copy_to_system("x") == ""


def test_a_broken_helper_does_not_raise(monkeypatch):
    monkeypatch.setattr(terminal.shutil, "which", lambda name: "/usr/bin/wl-copy")

    def boom(command, **kwargs):
        raise OSError("gone")

    monkeypatch.setattr(terminal.subprocess, "run", boom)
    assert terminal.copy_to_system("x") == ""


def test_notify_send_is_called_as_eirene(monkeypatch):
    seen = {}
    monkeypatch.setattr(notify, "IS_MAC", False)
    monkeypatch.setattr(notify, "IS_WINDOWS", False)
    monkeypatch.setattr(notify.shutil, "which", lambda name: "/usr/bin/notify-send")
    monkeypatch.setattr(notify, "_replaceable", lambda: False)
    monkeypatch.setattr(notify.subprocess, "Popen",
                        lambda command, **kw: seen.setdefault("command", command))
    assert notify.send("my chat", "all done") is True
    command = seen["command"]
    assert command[0] == "notify-send"
    assert "-a" in command and "Eirene" in command
    assert command[-2:] == ["my chat", "all done"]


def test_the_notification_carries_the_logo(monkeypatch):
    seen = {}
    monkeypatch.setattr(notify, "IS_MAC", False)
    monkeypatch.setattr(notify, "IS_WINDOWS", False)
    monkeypatch.setattr(notify.shutil, "which", lambda name: "/usr/bin/notify-send")
    monkeypatch.setattr(notify, "_replaceable", lambda: False)
    monkeypatch.setattr(notify.subprocess, "Popen",
                        lambda command, **kw: seen.setdefault("command", command))
    notify.send("chat", "body")
    assert "-i" in seen["command"], "the logo should be passed"
    icon = seen["command"][seen["command"].index("-i") + 1]
    assert icon.endswith("Eirene.png")
    assert "transparent" not in icon


def test_a_new_notification_replaces_the_last_one(monkeypatch):
    import io
    launched = []

    class Waiting:
        def __init__(self, argv, **kw):
            self.argv, self.alive = argv, True
            self.stdout = io.StringIO("41\n")
            launched.append(self)

        def poll(self):
            return None if self.alive else 0

        def terminate(self):
            self.alive = False

        kill = terminate

        def wait(self):
            return 0

    monkeypatch.setattr(notify.subprocess, "Popen", Waiting)
    monkeypatch.setattr(notify, "_last_id", 0)
    monkeypatch.setattr(notify, "_waiter", None)
    monkeypatch.setattr(notify, "_wait_for_click", lambda process, read: None)
    notify._send_replacing("chat", "first")
    notify._send_replacing("chat", "second")
    first, second = launched
    assert "-r" not in first.argv and not first.alive
    assert second.argv[second.argv.index("-r") + 1] == "41"
    assert "-A" in second.argv and second.argv[-2:] == ["chat", "second"]


def test_the_logo_ships_with_the_source():
    from pathlib import Path
    logo = Path(__file__).resolve().parents[1] / "img" / "Eirene.png"
    assert logo.exists()
    assert notify.icon_path() == str(logo)


def test_notifications_are_skipped_without_a_tool(monkeypatch):
    monkeypatch.setattr(notify.shutil, "which", lambda name: None)
    assert notify.available() is False
    assert notify.send("chat", "body") is False


def test_a_broken_notifier_does_not_raise(monkeypatch):
    monkeypatch.setattr(notify, "IS_MAC", False)
    monkeypatch.setattr(notify, "IS_WINDOWS", False)
    monkeypatch.setattr(notify.shutil, "which", lambda name: "/usr/bin/notify-send")

    def boom(command, **kwargs):
        raise OSError("gone")

    monkeypatch.setattr(notify.subprocess, "Popen", boom)
    assert notify.send("chat", "body") is False


def test_macos_uses_osascript(monkeypatch):
    monkeypatch.setattr(notify, "IS_MAC", True)
    monkeypatch.setattr(notify, "IS_WINDOWS", False)
    monkeypatch.setattr(notify.shutil, "which",
                        lambda name: "/mock/osascript" if name == "osascript" else None)
    command = notify._command("chat", 'say "hi"')
    assert command[0] == "osascript"
    assert "Eirene" in command[2]
    assert '\\"hi\\"' in command[2]


def test_windows_uses_powershell(monkeypatch):
    monkeypatch.setattr(notify, "IS_MAC", False)
    monkeypatch.setattr(notify, "IS_WINDOWS", True)
    monkeypatch.setattr(notify.shutil, "which",
                        lambda name: "/mock/powershell" if name == "powershell" else None)
    command = notify._command("chat", "done")
    assert command[0] == "powershell"
    assert "BalloonTipTitle" in command[-1]


@pytest.mark.parametrize("tool,expected", [
    ("notify-send", "notify-send"),
    ("kdialog", "kdialog"),
    ("zenity", "zenity"),
    ("gdbus", "gdbus"),
    ("dbus-send", "dbus-send"),
])
def test_every_linux_desktop_has_a_notifier(tool, expected, monkeypatch):
    monkeypatch.setattr(notify, "IS_MAC", False)
    monkeypatch.setattr(notify, "IS_WINDOWS", False)
    monkeypatch.setattr(notify.shutil, "which",
                        lambda name: f"/usr/bin/{name}" if name == tool else None)
    assert notify.available() is True
    command = notify._command("my chat", "all done")
    assert command[0] == expected
    joined = " ".join(command)
    assert "Eirene" in joined
    assert "my chat" in joined


def test_the_best_linux_notifier_wins(monkeypatch):
    monkeypatch.setattr(notify, "IS_MAC", False)
    monkeypatch.setattr(notify, "IS_WINDOWS", False)
    monkeypatch.setattr(notify.shutil, "which",
                        lambda name: f"/usr/bin/{name}"
                        if name in ("kdialog", "notify-send") else None)
    assert notify.linux_tool() == "notify-send"


def test_kde_gets_a_passive_popup(monkeypatch):
    monkeypatch.setattr(notify, "IS_MAC", False)
    monkeypatch.setattr(notify, "IS_WINDOWS", False)
    monkeypatch.setattr(notify.shutil, "which",
                        lambda name: "/usr/bin/kdialog" if name == "kdialog" else None)
    command = notify._command("chat", "done")
    assert "--passivepopup" in command
    assert command[-1].isdigit()


def test_macos_prefers_terminal_notifier(monkeypatch):
    monkeypatch.setattr(notify, "IS_MAC", True)
    monkeypatch.setattr(notify, "IS_WINDOWS", False)
    monkeypatch.setattr(notify.shutil, "which",
                        lambda name: "/usr/local/bin/terminal-notifier"
                        if name == "terminal-notifier" else None)
    command = notify._command("chat", "done")
    assert command[0] == "terminal-notifier"
    assert "-appIcon" in command


def test_macos_replaces_and_opens_the_terminal(monkeypatch):
    monkeypatch.setattr(notify, "IS_MAC", True)
    monkeypatch.setattr(notify, "IS_WINDOWS", False)
    monkeypatch.setattr(notify.shutil, "which",
                        lambda name: "/usr/local/bin/terminal-notifier"
                        if name == "terminal-notifier" else None)
    monkeypatch.setenv("__CFBundleIdentifier", "com.googlecode.iterm2")
    command = notify._command("chat", "done")
    assert command[command.index("-group") + 1] == f"eirene-{os.getpid()}"
    assert command[command.index("-activate") + 1] == "com.googlecode.iterm2"


def test_windows_toast_replaces_the_last_one(monkeypatch):
    launched = []

    class Waiting:
        def __init__(self, argv, **kw):
            self.argv, self.env, self.alive = argv, kw["env"], True
            self.stdout = io.BytesIO(b"shown\n")
            launched.append(self)

        def poll(self):
            return None if self.alive else 0

        def terminate(self):
            self.alive = False

        def wait(self):
            return 0

    monkeypatch.setattr(notify, "IS_WINDOWS", True)
    monkeypatch.setattr(notify.subprocess, "Popen", Waiting)
    monkeypatch.setattr(notify, "_waiter", None)
    notify._send_windows("chat", "first")
    notify._send_windows("chat", "it's <done>")
    first, second = launched
    assert not first.alive and second.alive
    assert second.argv[0] == "powershell" and "-EncodedCommand" in second.argv
    assert second.env["EIRENE_TOAST_BODY"] == "it's <done>"
    assert second.env["EIRENE_TOAST_GROUP"] == first.env["EIRENE_TOAST_GROUP"]


@pytest.mark.skipif(os.name != "nt", reason="needs Windows PowerShell")
def test_windows_toast_script_parses():
    import subprocess
    check = ("$errors = $null; $null = [System.Management.Automation.Language.Parser]::ParseInput("
             "$env:EIRENE_SCRIPT, [ref]$null, [ref]$errors); $errors.Count")
    result = subprocess.run(["powershell", "-NoProfile", "-Command", check], capture_output=True,
                            text=True, env={**os.environ, "EIRENE_SCRIPT": notify.WINDOWS_TOAST})
    assert result.stdout.strip() == "0", result.stdout + result.stderr


def test_macos_falls_back_to_osascript(monkeypatch):
    monkeypatch.setattr(notify, "IS_MAC", True)
    monkeypatch.setattr(notify, "IS_WINDOWS", False)
    monkeypatch.setattr(notify.shutil, "which",
                        lambda name: "/usr/bin/osascript"
                        if name == "osascript" else None)
    assert notify.available() is True
    assert notify._command("chat", "done")[0] == "osascript"


def test_windows_uses_pwsh_when_present(monkeypatch):
    monkeypatch.setattr(notify, "IS_MAC", False)
    monkeypatch.setattr(notify, "IS_WINDOWS", True)
    monkeypatch.setattr(notify.shutil, "which",
                        lambda name: "C:/pwsh.exe" if name == "pwsh" else None)
    assert notify.available() is True
    assert notify._command("chat", "done")[0] == "pwsh"


def test_a_bare_linux_box_reports_no_notifier(monkeypatch):
    monkeypatch.setattr(notify, "IS_MAC", False)
    monkeypatch.setattr(notify, "IS_WINDOWS", False)
    monkeypatch.setattr(notify.shutil, "which", lambda name: None)
    assert notify.linux_tool() == ""
    assert notify.available() is False


def test_osc52_long_copies_survive_gnu_screen():
    import base64
    import re
    text = "copied over ssh " * 400
    wrapped = terminal.osc52(text, {"STY": "1.pts"})
    pieces = re.findall(r"\x1bP(.*?)\x1b\\", wrapped, re.DOTALL)
    assert pieces and all(len(piece) <= terminal.SCREEN_CHUNK for piece in pieces)
    assert "".join(pieces) == terminal.osc52(text, {})
    payload = "".join(pieces)[len("\x1b]52;c;"):-1]
    assert base64.b64decode(payload).decode() == text


def test_windows_clipboard_receives_utf16_without_a_byte_order_mark(monkeypatch):
    sent = {}
    monkeypatch.setattr(terminal, "clipboard_tool", lambda: ["clip.exe"])
    monkeypatch.setattr(terminal.subprocess, "run",
                        lambda command, **kwargs: sent.update(kwargs) or SimpleNamespace(returncode=0))
    assert terminal.copy_to_system("C:\\Users\\Jürgen 日本") == "clip.exe"
    assert sent["input"] == "C:\\Users\\Jürgen 日本".encode("utf-16-le")


async def test_tab_title_drops_prefix_once_the_chat_is_named(workdir):
    from test_tui import start
    app, pilot, context = await start(workdir)
    try:
        app.session.name = ""
        assert app.tab_label() == "eirene"
        app.session.name = "Fixing windows test failures"
        assert app.tab_label() == "Fixing windows test failures"
    finally:
        await context.__aexit__(None, None, None)


async def test_clear_restores_the_default_title(workdir):
    from test_tui import start
    from eirene.commands import dispatch
    import eirene.app as app_mod
    app, pilot, context = await start(workdir)
    titles = []
    original = app_mod.write_terminal_title
    app_mod.write_terminal_title = lambda driver, text: titles.append(text) or True
    try:
        app.session.name = "Fixing windows test failures"
        app.name_the_tab()
        assert titles[-1] == "Fixing windows test failures"
        await dispatch(app, "/clear")
        await pilot.pause()
        assert titles[-1] == app_mod.UNNAMED_TITLE
    finally:
        app_mod.write_terminal_title = original
        await context.__aexit__(None, None, None)


async def test_window_title_spinner_matches_the_chat(workdir, monkeypatch):
    from test_tui import start
    import eirene.app as app_mod
    from eirene.ui import art
    app, pilot, context = await start(workdir)
    titles = []
    monkeypatch.setattr(app_mod, "write_terminal_title", lambda driver, text: titles.append(text) or True)
    try:
        app.status._spinner_style = 2  # the half moon
        app.config.set("reduce_motion", False)
        app._busy = True
        for tick in range(4):
            app._tab_tick = tick
            app.name_the_tab()
        assert [t.split()[0] for t in titles[-4:]] == list(art.MOON_SPINNER)
        app.config.set("reduce_motion", True)
        app.name_the_tab()
        assert titles[-1].startswith("* ")
    finally:
        app._busy = False
        await context.__aexit__(None, None, None)


async def test_turns_in_one_session_share_a_spinner(workdir):
    from test_tui import start, Script, type_line
    from eirene.providers.base import Done, TextDelta
    from eirene.ui import art
    app, pilot, context = await start(workdir, Script([TextDelta("ok"), Done("stop")]))
    try:
        seen = []
        for prompt in ("one", "two", "three"):
            await type_line(pilot, prompt)
            seen.append(app.status.spinner_style)
            for _ in range(40):
                if app.turn and app.turn.done():
                    break
                await pilot.pause(0.05)
        assert seen == [art.session_spinner(app.session.id)] * 3
    finally:
        await context.__aexit__(None, None, None)


def test_windows_toast_avoids_the_winrt_event_cmdlet():
    # Windows PowerShell 5.1 refuses it, which used to stop the toast from ever showing.
    assert "Register-ObjectEvent" not in notify.WINDOWS_TOAST
    assert notify.WINDOWS_TOAST.index("ToastClick]::Watch") < notify.WINDOWS_TOAST.index(".Show($toast)")


@pytest.mark.parametrize("output, shown", [(b"shown\n", True), (b"", False)])
def test_windows_toast_reports_whether_it_appeared(monkeypatch, output, shown):
    class Process:
        def __init__(self, *args, **kwargs):
            self.stdout = io.BytesIO(output)

        def poll(self):
            return 0

    monkeypatch.setattr(notify, "_waiter", None)
    monkeypatch.setattr(notify, "_sender", None)
    monkeypatch.setattr(notify, "_toast_shown", True)
    monkeypatch.setattr(notify.subprocess, "Popen", Process)
    notify._send_windows("chat", "body")
    assert notify.toast_shown() is shown
