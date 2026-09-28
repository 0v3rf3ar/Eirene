"""Clipboard, terminal title and desktop notifications."""

from __future__ import annotations

import subprocess

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
    monkeypatch.setattr(notify.subprocess, "Popen",
                        lambda command, **kw: seen.setdefault("command", command))
    notify.send("chat", "body")
    assert "-i" in seen["command"], "the logo should be passed"
    icon = seen["command"][seen["command"].index("-i") + 1]
    assert icon.endswith("Eirene.png")
    assert "transparent" not in icon


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
