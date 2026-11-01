"""The interface survives bad input, failing handlers and broken decorations."""

from __future__ import annotations

import os
import threading
import time

import pytest
from rich.console import Console
from textual import events

from eirene.app import Eirene
from eirene.core import crash
from eirene.core.attachments import MAX_DROP_CHARS, dropped_paths
from eirene.ui import composer, guard, links
from eirene.ui.chat import AnswerBlock, NoticeBlock


def make_app(workdir, *, contain=True) -> Eirene:
    app = Eirene(workdir)
    app.CONTAIN_ERRORS = contain
    app.config.set("seasonal_effects", False)
    app.config.set("companion", False)
    return app


def notices(app) -> list[str]:
    return [block.content.plain for block in app.query(NoticeBlock)]


# The crash in the bug report: a paste that starts with "~name".

@pytest.mark.parametrize("text", ["~nosuchuser-eirene/notes.txt", "~nosuchuser-eirene",
                                  "~~~", "~/" + "x" * 5000, "a\x00b", "file://%00",
                                  "'unterminated", "\\\\server\\share\\file.txt"])
def test_dropped_paths_never_raises_for_ordinary_text(workdir, text):
    assert dropped_paths(text, workdir) == []


def test_dropped_paths_ignores_oversized_pastes_without_scanning_them(workdir, monkeypatch):
    target = workdir / "real.txt"
    target.touch()
    monkeypatch.setattr("eirene.core.attachments.shlex.split",
                        lambda *args, **kwargs: pytest.fail("split an oversized paste"))
    assert dropped_paths(str(target) + " " * MAX_DROP_CHARS + "x", workdir) == []


def test_dropped_paths_stops_at_the_first_word_that_is_not_a_file(workdir, monkeypatch):
    checked = []
    real = workdir / "real.txt"
    real.touch()
    original = dropped_paths.__globals__["_dropped_file"]
    monkeypatch.setitem(dropped_paths.__globals__, "_dropped_file",
                        lambda value, root: checked.append(value) or original(value, root))
    assert dropped_paths(f"{real} prose " + "word " * 1000, workdir) == []
    assert len(checked) <= 3


async def test_pasting_a_tilde_word_inserts_text_instead_of_crashing(workdir):
    app = make_app(workdir, contain=False)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        app.prompt.post_message(events.Paste("~nosuchuser-eirene/notes.txt"))
        await pilot.pause()
        assert app.prompt.text == "~nosuchuser-eirene/notes.txt"


async def test_paste_strips_terminal_control_sequences(workdir):
    app = make_app(workdir, contain=False)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        app.prompt.post_message(events.Paste("\x1b[31mred\x1b[0m \x1b]0;title\x07ok\ud800"))
        await pilot.pause()
        assert app.prompt.text == "red ok"


async def test_slow_path_check_falls_back_to_text(workdir, monkeypatch):
    def hang(text, root):
        time.sleep(1)
        return [root]
    monkeypatch.setattr(composer, "dropped_paths", hang)
    monkeypatch.setattr(composer, "DROP_CHECK_SECONDS", 0.05)
    app = make_app(workdir, contain=False)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        app.prompt.post_message(events.Paste("\\\\sleeping-share\\notes.txt"))
        await pilot.pause(0.3)
        assert app.prompt.text == "\\\\sleeping-share\\notes.txt"


# Containment.

async def test_failing_handler_is_contained_and_the_widget_keeps_working(workdir, monkeypatch):
    def broken(text, root):
        raise RuntimeError("Could not determine home directory.")
    monkeypatch.setattr(composer, "dropped_paths", broken)
    app = make_app(workdir)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        app.prompt.post_message(events.Paste("~x"))
        await pilot.pause()
        await pilot.pause()
        assert app.is_running
        assert any("Something went wrong (RuntimeError: Could not determine home directory.)" in text
                   for text in notices(app))
        # Textual stops a widget's message loop after an escaped error; the
        # guard must keep the prompt alive so later keys still arrive.
        await pilot.press("o", "k")
        assert app.prompt.text == "ok"
    reports = crash.recent()
    assert reports
    body = reports[0].read_text(encoding="utf-8")
    assert "where: Prompt#prompt.on_paste" in body
    assert "fatal: no" in body
    assert "RuntimeError: Could not determine home directory." in body


async def test_failed_background_task_is_reported_not_lost(workdir):
    app = make_app(workdir)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        async def fails():
            raise ValueError("background bug")
        app.spawn(fails(), name="probe")
        await pilot.pause()
        await pilot.pause()
        assert app.is_running
        assert any("ValueError: background bug" in text for text in notices(app))
    assert "where: task eirene:probe" in crash.recent()[0].read_text(encoding="utf-8")


async def test_failed_timer_callback_is_contained(workdir):
    app = make_app(workdir)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        def tick():
            raise KeyError("timer bug")
        app.set_timer(0.01, tick)
        await pilot.pause(0.1)
        assert app.is_running
        assert any("KeyError" in text for text in notices(app))


async def test_crash_loop_exhausts_the_budget_and_exits(workdir, monkeypatch):
    app = make_app(workdir)
    app._error_budget = guard.ErrorBudget(limit=2, window=60)

    def broken(text, root):
        locals_with_a_secret = "sk-secret-value"  # noqa: F841
        raise RuntimeError("again")
    monkeypatch.setattr(composer, "dropped_paths", broken)
    with pytest.raises(RuntimeError, match="again"):
        async with app.run_test(size=(100, 32)) as pilot:
            for _ in range(4):
                app.prompt.post_message(events.Paste("~x"))
                await pilot.pause()
    assert app.return_code == 1
    assert app.crash_report is not None
    assert "fatal: yes" in app.crash_report.read_text(encoding="utf-8")


def test_fatal_output_omits_local_variables(workdir):
    app = Eirene(workdir)
    try:
        api_key = "-".join(("sk", "secret", "value"))  # only in locals, not in source  # noqa: F841
        raise RuntimeError("fatal")
    except RuntimeError as error:
        app._fatal = (error, None)
    app._close_messages_no_wait = lambda: None
    app._fatal_error()
    console = Console(record=True, width=120)
    for renderable in app._exit_renderables:
        console.print(renderable)
    output = console.export_text()
    assert "RuntimeError: fatal" in output
    assert "sk-secret-value" not in output
    assert "Eirene stopped after an unexpected error." in output


def test_error_budget_window():
    now = [0.0]
    budget = guard.ErrorBudget(limit=2, window=10, clock=lambda: now[0])
    assert budget.spend() and budget.spend()
    assert not budget.spend()
    now[0] = 11.0
    assert budget.spend()


def test_guard_leaves_other_apps_alone():
    from textual.app import App

    assert guard.install()
    assert getattr(App, "contain_error", None) is None


# Crash reports.

def test_crash_report_is_private_and_pruned():
    for index in range(crash.KEEP_REPORTS + 3):
        try:
            raise ValueError(f"error {index}")
        except ValueError as error:
            report = crash.record(error, where="test")
    assert report is not None and report.is_file()
    if os.name != "nt":
        assert report.stat().st_mode & 0o777 == 0o600
    assert len(crash.recent(limit=100)) == crash.KEEP_REPORTS
    assert "ValueError: error" in report.read_text(encoding="utf-8")


def test_crash_record_never_raises(monkeypatch):
    monkeypatch.setattr(crash, "_write", lambda *args, **kwargs: 1 / 0)
    assert crash.record(RuntimeError("x"), where="test") is None


def test_summary_is_one_bounded_line():
    text = crash.summary(ValueError("line one\nline two " + "x" * 500))
    assert "\n" not in text
    assert text.startswith("ValueError: line one line two")
    assert len(text) <= crash.SUMMARY_CHARS + len("ValueError: ")


# Links.

@pytest.mark.parametrize("url, expected", [
    ("https://example.com/docs", True),
    ("http://localhost:8080/x", True),
    ("mailto:someone@example.com", True),
    ("HTTPS://EXAMPLE.COM", True),
    ("https://", False),
    ("C:\\Windows\\System32\\calc.exe", False),
    ("file:///etc/passwd", False),
    ("javascript:alert(1)", False),
    ("./README.md", False),
    ("https://example.com/\x1b]0;x", False),
    ("https://example.com/" + "a" * links.MAX_URL_CHARS, False),
    ("", False),
])
def test_only_web_and_mail_links_are_launchable(url, expected):
    assert links.launchable(url) is expected


async def test_unsafe_link_is_copied_never_launched(workdir, monkeypatch):
    monkeypatch.setattr(links, "open_external", lambda url: pytest.fail(f"launched {url}"))
    app = make_app(workdir, contain=False)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        app.open_url("C:\\Windows\\System32\\calc.exe")
        await pilot.pause()
        assert app._clipboard == "C:\\Windows\\System32\\calc.exe"
        assert any("only web and mail links" in text for text in notices(app))


async def test_link_launches_off_the_event_loop_and_failures_become_a_notice(workdir, monkeypatch):
    threads = []

    def fail(url):
        threads.append(threading.current_thread())
        raise links.LinkError("no desktop link handler (xdg-open) is installed")
    monkeypatch.setattr(links, "open_external", fail)
    app = make_app(workdir, contain=False)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        app.open_url("https://example.com/docs")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert threads and threads[0] is not threading.main_thread()
        assert app._clipboard == "https://example.com/docs"
        assert any("couldn't open the link" in text for text in notices(app))


def test_posix_launcher_falls_through_and_reports(monkeypatch):
    monkeypatch.setattr(links.os, "name", "posix")
    monkeypatch.setattr(links.sys, "platform", "linux")
    monkeypatch.setattr(links.shutil, "which", lambda name: name if name in {"xdg-open", "gio"} else None)
    calls = []

    def run(argv):
        calls.append(argv[0])
        if argv[0] == "xdg-open":
            raise links.LinkError("xdg-open exited with status 3")
    monkeypatch.setattr(links, "_run", run)
    links.open_external("https://example.com")
    assert calls == ["xdg-open", "gio"]


def test_posix_launcher_without_handlers_raises(monkeypatch):
    monkeypatch.setattr(links.os, "name", "posix")
    monkeypatch.setattr(links.sys, "platform", "linux")
    monkeypatch.setattr(links.shutil, "which", lambda name: None)
    with pytest.raises(links.LinkError, match="no desktop link handler"):
        links.open_external("https://example.com")


def test_link_widgets_share_the_open_action():
    from eirene.ui.aside import AsideText

    for widget in (NoticeBlock, AnswerBlock, AsideText):
        assert issubclass(widget, links.OpensLinks)


# Decorations.

def test_portrait_failure_drops_the_picture_not_the_frame():
    from eirene.ui.sixel_portrait import PortraitUpdate

    class Update:
        def render_segments(self, console):
            return "frame"

    class Portrait:
        broken = False

        @property
        def parent(self):
            raise LookupError("unmounted")

    portrait = Portrait()
    update = PortraitUpdate(Update(), portrait)
    assert update.render_segments(None) == "frame"
    assert portrait.broken
    assert update.render_segments(None) == "frame"


# Terminal input decoding.

@pytest.mark.skipif(os.name == "nt", reason="POSIX terminal driver")
def test_posix_input_decoder_replaces_invalid_bytes():
    from textual.drivers import linux_driver

    from eirene.ui import input_guard

    input_guard.install()
    decode = linux_driver.getincrementaldecoder("utf-8")().decode
    assert decode(b"ok \xed\xa0\x80 \xff") == "ok ��� �"
    # Multibyte characters split across reads still join up.
    assert decode(b"\xf0\x9f") == "" and decode(b"\x98\x80") == "😀"


def test_console_batches_rejoin_a_split_surrogate_pair():
    from eirene.ui.input_guard import join_console_keys

    high, low = "\ud83d", "\ude00"  # "😀" as the console delivers it
    text, carried = join_console_keys("", list("abc") + [high])
    assert (text, carried) == ("abc", high)
    text, carried = join_console_keys(carried, [low, "d"])
    assert (text, carried) == ("😀d", "")


def test_console_batches_replace_unpaired_surrogates():
    from eirene.ui.input_guard import join_console_keys

    assert join_console_keys("", ["a", "\ude00", "b"]) == ("a�b", "")
    assert join_console_keys("\ud83d", ["x"]) == ("�x", "")
