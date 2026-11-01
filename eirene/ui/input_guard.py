"""Make Textual's terminal input threads survive any input the terminal sends.

Textual reads the terminal on a background thread and decodes strictly:

* POSIX drivers use a strict incremental UTF-8 decoder. One invalid byte (a
  binary clipboard, a Latin-1 terminal, a mangled SSH stream) raises in the
  input thread, and the app panics and exits.
* The Windows console monitor reads key records in batches of up to 1024 and
  decodes each batch as UTF-16 on its own. A paste whose emoji straddles two
  batches leaves a lone surrogate; the decode raises, the monitor thread ends,
  and the app stays on screen but never sees another key or click.

Both become lossy instead: undecodable input turns into U+FFFD, and a high
surrogate at the end of a batch waits for its partner in the next one.
"""

from __future__ import annotations

import codecs
import functools
import importlib
import sys
from collections.abc import Callable

POSIX_DRIVERS = ("textual.drivers.linux_driver", "textual.drivers.linux_inline_driver")
# Names the Windows monitor loop below takes from Textual's win32 module.
WIN32_NAMES = ("EventMonitor", "XTermParser", "constants", "wintypes", "byref",
               "GetStdHandle", "STD_INPUT_HANDLE", "INPUT_RECORD", "KERNEL32",
               "wait_for_handles")
# Consecutive failed reads after which the console is considered gone.
MAX_READ_FAILURES = 50

_installed = False


def lenient_decoder(encoding: str) -> Callable[..., codecs.IncrementalDecoder]:
    """Stand-in for codecs.getincrementaldecoder that never raises on bad input."""
    return functools.partial(codecs.getincrementaldecoder(encoding), errors="replace")


def join_console_keys(pending: str, keys: list[str]) -> tuple[str, str]:
    """Decode one batch of console key characters; return (text, carried high surrogate)."""
    text = pending + "".join(keys)
    carried = ""
    if text and "\ud800" <= text[-1] <= "\udbff":
        text, carried = text[:-1], text[-1]
    # Pairs split by the console recombine here; anything still unpaired is replaced.
    return text.encode("utf-16", "surrogatepass").decode("utf-16", "replace"), carried


def install() -> None:
    """Patch once per process; a Textual layout this does not recognise is left alone."""
    global _installed
    if _installed:
        return
    _installed = True
    for name in POSIX_DRIVERS:
        try:
            module = importlib.import_module(name)
        except Exception:  # noqa: BLE001 - e.g. termios is missing on Windows
            continue
        if getattr(module, "getincrementaldecoder", None) is codecs.getincrementaldecoder:
            module.getincrementaldecoder = lenient_decoder
    if sys.platform == "win32":
        _install_windows_monitor()


def _install_windows_monitor() -> None:
    try:
        from textual.drivers import win32
    except Exception:  # noqa: BLE001
        return
    if not all(hasattr(win32, name) for name in WIN32_NAMES):
        return
    base = win32.EventMonitor

    class LenientEventMonitor(base):  # type: ignore[misc, valid-type]
        """Textual's console monitor, with batch-safe decoding and a loop that outlives one bad batch."""

        def run(self) -> None:
            exit_requested = self.exit_event.is_set
            parser = win32.XTermParser(debug=win32.constants.DEBUG)
            read_count = win32.wintypes.DWORD(0)
            handle = win32.GetStdHandle(win32.STD_INPUT_HANDLE)
            max_events = 1024
            key_event_type = 0x0001
            resize_event_type = 0x0004
            records = (win32.INPUT_RECORD * max_events)()
            read_console_input = win32.KERNEL32.ReadConsoleInputW
            pending = ""
            failures = 0
            while not exit_requested():
                try:
                    for event in parser.tick():
                        self.process_event(event)
                    if win32.wait_for_handles([handle], 100) is None:
                        continue
                    read_console_input(handle, win32.byref(records), max_events,
                                       win32.byref(read_count))
                    keys: list[str] = []
                    new_size: tuple[int, int] | None = None
                    for record in records[:read_count.value]:
                        if record.EventType == key_event_type:
                            key_event = record.Event.KeyEvent
                            if not key_event.bKeyDown:
                                continue
                            if key_event.dwControlKeyState and key_event.wVirtualKeyCode == 0:
                                continue
                            keys.append(key_event.uChar.UnicodeChar)
                        elif record.EventType == resize_event_type:
                            size = record.Event.WindowBufferSizeEvent.dwSize
                            new_size = (size.X, size.Y)
                    if keys or pending:
                        text, pending = join_console_keys(pending, keys)
                        for event in parser.feed(text):
                            self.process_event(event)
                    if new_size is not None:
                        self.on_size_change(*new_size)
                    failures = 0
                except Exception as error:  # noqa: BLE001 - keep reading the console
                    failures += 1
                    self.app.log.error("EVENT MONITOR ERROR", error)
                    if failures >= MAX_READ_FAILURES:
                        return

    win32.EventMonitor = LenientEventMonitor
