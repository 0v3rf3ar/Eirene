"""Pasting a picture from the clipboard attaches it as a file."""

from __future__ import annotations

import base64
import io
import os
import shlex
import subprocess
from pathlib import Path

import pytest
from PIL import Image
from textual import events

from eirene.app import Eirene
from eirene.core.attachments import attachment_path
from eirene.ui import clipboard
from eirene.ui.clipboard import ClipboardImage

posix_only = pytest.mark.skipif(os.name == "nt", reason="fake POSIX helpers")


def picture(kind: str = "PNG") -> bytes:
    data = io.BytesIO()
    Image.new("RGB", (3, 2), (200, 30, 90)).save(data, format=kind)
    return data.getvalue()


PNG = picture()


def fake_tool(bindir: Path, name: str, types: list[str], payloads: dict[str, bytes]) -> Path:
    """A clipboard helper that lists `types` and prints the payload for a requested type."""
    store = bindir / f"{name}-data"
    store.mkdir(parents=True, exist_ok=True)
    for kind, data in payloads.items():
        (store / kind.replace("/", "_")).write_bytes(data)
    listing = "\n".join(types)
    script = bindir / name
    script.write_text(f"""#!/bin/sh
last=""
for arg in "$@"; do
  case "$prev" in --type|-t) last="$arg";; esac
  prev="$arg"
done
case " $* " in
  *" --list-types "*|*" TARGETS "*) printf '%s\\n' {shlex.quote(listing)}; exit 0;;
esac
file={shlex.quote(str(store))}/$(printf '%s' "$last" | tr / _)
[ -f "$file" ] || exit 1
cat "$file"
""")
    script.chmod(0o755)
    return script


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    """A Linux desktop whose only clipboard tools are fakes in a private bin directory."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    monkeypatch.setattr(clipboard.sys, "platform", "linux")
    monkeypatch.setattr(clipboard, "_wsl", lambda: False)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}/usr/bin{os.pathsep}/bin")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    return bindir


@posix_only
def test_wayland_png(desktop, monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    fake_tool(desktop, "wl-paste", ["text/plain", "image/png"], {"image/png": PNG})
    assert clipboard.read_image() == ClipboardImage(PNG, "image/png")


@posix_only
def test_x11_png(desktop, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    fake_tool(desktop, "xclip", ["TARGETS", "UTF8_STRING", "image/png"], {"image/png": PNG})
    assert clipboard.read_image() == ClipboardImage(PNG, "image/png")


@posix_only
def test_wayland_is_preferred_and_x11_is_the_fallback(desktop, monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("DISPLAY", ":0")
    fake_tool(desktop, "wl-paste", ["text/plain"], {})
    fake_tool(desktop, "xclip", ["image/png"], {"image/png": PNG})
    assert clipboard.read_image() == ClipboardImage(PNG, "image/png")


@posix_only
def test_bmp_is_converted_to_png(desktop, monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    fake_tool(desktop, "wl-paste", ["image/bmp"], {"image/bmp": picture("BMP")})
    image = clipboard.read_image()
    assert image is not None and image.mime_type == "image/png"
    with Image.open(io.BytesIO(image.data)) as decoded:
        assert decoded.size == (3, 2) and decoded.getpixel((0, 0)) == (200, 30, 90)


@posix_only
def test_jpeg_keeps_its_format_and_extension(desktop, monkeypatch):
    jpeg = picture("JPEG")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    fake_tool(desktop, "wl-paste", ["image/jpeg"], {"image/jpeg": jpeg})
    image = clipboard.read_image()
    assert image == ClipboardImage(jpeg, "image/jpeg") and image.filename == "pasted-image.jpg"


@posix_only
@pytest.mark.parametrize("types, payloads", [
    (["text/plain", "UTF8_STRING"], {}),                 # text only
    (["image/bmp"], {"image/bmp": b"not a bitmap"}),     # damaged picture
    (["image/png"], {}),                                 # offered, then refused
])
def test_no_usable_picture_is_none(desktop, monkeypatch, types, payloads):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    fake_tool(desktop, "wl-paste", types, payloads)
    assert clipboard.read_image() is None


@posix_only
def test_no_display_or_no_tools_is_none(desktop, monkeypatch):
    fake_tool(desktop, "wl-paste", ["image/png"], {"image/png": PNG})
    assert clipboard.read_image() is None          # no WAYLAND_DISPLAY
    monkeypatch.setenv("DISPLAY", ":0")
    assert clipboard.read_image() is None          # X11 but no xclip


@posix_only
def test_a_hung_helper_times_out(desktop, monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    (desktop / "wl-paste").write_text("#!/bin/sh\nsleep 30\n")
    (desktop / "wl-paste").chmod(0o755)
    monkeypatch.setattr(clipboard, "HELPER_SECONDS", 0.3)
    assert clipboard.read_image() is None


def test_over_ssh_the_server_clipboard_is_never_read(monkeypatch):
    monkeypatch.setenv("SSH_CONNECTION", "10.0.0.2 50000 10.0.0.1 22")
    monkeypatch.setattr(clipboard.subprocess, "run",
                        lambda *args, **kwargs: pytest.fail("read the server's clipboard"))
    assert clipboard.read_image() is None


def test_windows_reads_powershell_base64(monkeypatch):
    calls = []
    monkeypatch.setattr(clipboard.sys, "platform", "win32")
    monkeypatch.setattr(clipboard.os, "name", "nt")
    monkeypatch.setattr(clipboard.shutil, "which",
                        lambda name: "C:/Windows/powershell.exe" if name == "powershell.exe" else None)
    monkeypatch.setattr(clipboard, "_run",
                        lambda argv: calls.append(argv) or base64.b64encode(PNG) + b"\r\n")
    assert clipboard.read_image() == ClipboardImage(PNG, "image/png")
    script = calls[0][-1]
    assert "-Sta" in calls[0]
    # The lossless PNG format is tried before the alpha-less bitmap.
    assert script.index("GetData('PNG')") < script.index("GetImage()")


def test_wsl_uses_windows_powershell(monkeypatch):
    monkeypatch.setattr(clipboard.sys, "platform", "linux")
    monkeypatch.setattr(clipboard, "_wsl", lambda: True)
    monkeypatch.setattr(clipboard.shutil, "which",
                        lambda name: "/mnt/c/WINDOWS/powershell.exe" if name == "powershell.exe" else None)
    monkeypatch.setattr(clipboard, "_run", lambda argv: base64.b64encode(PNG))
    assert clipboard.read_image() == ClipboardImage(PNG, "image/png")


def test_windows_without_a_picture_is_none(monkeypatch):
    monkeypatch.setattr(clipboard.sys, "platform", "win32")
    monkeypatch.setattr(clipboard.os, "name", "nt")
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: "powershell.exe")
    monkeypatch.setattr(clipboard, "_run", lambda argv: None)
    assert clipboard.read_image() is None


def test_macos_writes_the_png_flavour_to_a_private_file(monkeypatch):
    monkeypatch.setattr(clipboard.sys, "platform", "darwin")

    def osascript(argv):
        script = " ".join(argv)
        assert argv[0] == "osascript" and "«class PNGf»" in script
        target = script.split('POSIX file "')[1].split('"')[0]
        Path(target).write_bytes(PNG)
        return b""
    monkeypatch.setattr(clipboard, "_run", osascript)
    assert clipboard.read_image() == ClipboardImage(PNG, "image/png")


def test_macos_without_a_picture_is_none(monkeypatch):
    monkeypatch.setattr(clipboard.sys, "platform", "darwin")
    monkeypatch.setattr(clipboard, "_run", lambda argv: None)
    assert clipboard.read_image() is None


@posix_only
def test_helpers_never_inherit_the_terminal(monkeypatch):
    seen = {}

    def run(argv, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 1, b"", b"")
    monkeypatch.setattr(clipboard.subprocess, "run", run)
    clipboard._run(["wl-paste"])
    assert seen["stdin"] is subprocess.DEVNULL and seen["capture_output"] is True


# In the interface.

def make_app(workdir) -> Eirene:
    app = Eirene(workdir)
    app.config.set("seasonal_effects", False)
    app.config.set("companion", False)
    return app


@pytest.mark.parametrize("key", ["ctrl+v", "alt+v"])
async def test_paste_key_attaches_the_clipboard_picture(workdir, monkeypatch, key):
    monkeypatch.setattr(clipboard, "read_image", lambda: ClipboardImage(PNG, "image/png"))
    app = make_app(workdir)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        app.prompt.value = "what is this? "
        await pilot.press(key)
        await pilot.pause()
        await pilot.press(key)
        await pilot.pause()
        assert app.prompt.text == "what is this? [pasted-image.png][pasted-image.png (2)]"
        items = list(app.prompt._files.values())
        assert [item["mime_type"] for item in items] == ["image/png", "image/png"]
        assert all(attachment_path(item["id"]).read_bytes() == PNG for item in items)


async def test_without_a_picture_the_paste_key_pastes_text_as_before(workdir, monkeypatch):
    monkeypatch.setattr(clipboard, "read_image", lambda: None)
    app = make_app(workdir)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        app.copy_to_clipboard("copied inside eirene")
        await pilot.press("ctrl+v")
        await pilot.pause()
        assert app.prompt.text == "copied inside eirene"
        assert app.prompt._files == {}


async def test_an_empty_terminal_paste_checks_for_a_picture(workdir, monkeypatch):
    monkeypatch.setattr(clipboard, "read_image", lambda: ClipboardImage(PNG, "image/png"))
    app = make_app(workdir)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        app.prompt.post_message(events.Paste(""))
        await pilot.pause()
        await pilot.pause()
        assert app.prompt.text == "[pasted-image.png]"


async def test_secret_entry_never_takes_a_picture(workdir, monkeypatch):
    monkeypatch.setattr(clipboard, "read_image",
                        lambda: pytest.fail("read the clipboard during secret entry"))
    app = make_app(workdir)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        app.prompt.secret = True
        await pilot.press("ctrl+v")
        await pilot.pause()
        assert app.prompt._files == {}


async def test_oversized_picture_is_refused_with_a_reason(workdir, monkeypatch):
    monkeypatch.setattr(clipboard, "read_image", lambda: ClipboardImage(PNG, "image/png"))
    app = make_app(workdir)
    app.config.set("max_attachment_bytes", 10)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+v")
        await pilot.pause()
        await pilot.pause()
        assert app.prompt._files == {}
        notices = [block.content.plain for block in app.query("NoticeBlock")]
        assert any("exceeds" in notice for notice in notices)
