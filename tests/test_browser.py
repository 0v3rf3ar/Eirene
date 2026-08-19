"""Bounded browser tooling without requiring network access in tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from eirene.core.errors import ToolError
from eirene.tools import browser, registry


@pytest.fixture
def fake_chromium(tmp_path, monkeypatch):
    script = tmp_path / "fake_chromium.py"
    script.write_text(
        "import pathlib, sys\n"
        "for arg in sys.argv[1:]:\n"
        "    if arg.startswith('--screenshot='):\n"
        "        pathlib.Path(arg.split('=', 1)[1]).write_bytes(b'\\x89PNG\\r\\n\\x1a\\n')\n"
        "        raise SystemExit\n"
        "print('<html><body><main>rendered</main></body></html>')\n",
        encoding="utf-8")
    if os.name == "nt":
        executable = tmp_path / "chromium.cmd"
        executable.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        executable = tmp_path / "chromium"
        executable.write_text(f"#!{sys.executable}\nexec(open({str(script)!r}).read())\n",
                              encoding="utf-8")
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
    return executable


async def test_chromium_inspects_rendered_dom(fake_chromium):
    assert "<main>rendered</main>" in await browser.inspect("https://example.test")


async def test_chromium_screenshot_stays_in_workspace(fake_chromium, box, workdir):
    note = await browser.screenshot(box, "https://example.test", "artifacts/page.png")
    assert "artifacts/page.png" in note
    assert (workdir / "artifacts" / "page.png").read_bytes().startswith(b"\x89PNG")


def test_browser_rejects_local_files_and_credentials():
    with pytest.raises(ToolError, match="absolute"):
        browser._url("file:///etc/passwd")
    with pytest.raises(ToolError, match="credentials"):
        browser._url("https://user:secret@example.test")


def test_browser_override_supports_installations_outside_path(tmp_path, monkeypatch):
    binary = tmp_path / "Browser With Spaces"
    binary.write_bytes(b"browser")
    monkeypatch.setenv("EIRENE_CHROMIUM_PATH", str(binary))
    monkeypatch.setattr(browser.shutil, "which", lambda name: None)
    assert browser.executable() == str(binary)


def test_browser_override_reports_a_bad_path(tmp_path, monkeypatch):
    monkeypatch.setenv("EIRENE_CHROMIUM_PATH", str(tmp_path / "missing"))
    with pytest.raises(ToolError, match="EIRENE_CHROMIUM_PATH"):
        browser.executable()


def test_browser_has_native_windows_and_macos_install_locations(monkeypatch):
    monkeypatch.setattr(browser.sys, "platform", "darwin")
    assert any("Google Chrome.app" in str(path) for path in browser._installed_browsers())
    monkeypatch.setattr(browser.sys, "platform", "win32")
    monkeypatch.setenv("PROGRAMFILES", "C:/Program Files")
    assert any(str(path).lower().endswith("chrome.exe")
               for path in browser._installed_browsers())


def test_browser_uses_low_resource_background_flags(fake_chromium):
    argv = browser._argv("profile", 30)
    assert "--renderer-process-limit=2" in argv
    assert "--disable-background-networking" in argv


async def test_browser_tools_honor_network_isolation(box):
    with pytest.raises(ToolError, match="isolate_network"):
        await registry.execute("browser_inspect", {"url": "https://example.test"},
                               box, isolate_network=True)
    with pytest.raises(ToolError, match="isolate_network"):
        await registry.execute("web_search", {"query": "latest Python"},
                               box, isolate_network=True)
    with pytest.raises(ToolError, match="isolate_network"):
        await registry.execute("browser_interact", {
            "url": "https://example.test", "actions": [{"action": "text"}]},
            box, isolate_network=True)


def test_interactive_browser_schema_is_batched_and_bounded():
    spec = next(item for item in registry.specs() if item["name"] == "browser_interact")
    actions = spec["parameters"]["properties"]["actions"]
    assert actions["maxItems"] == 25
    assert {"click", "type", "evaluate", "dom", "text"}.issubset(
        actions["items"]["properties"]["action"]["enum"])


def test_search_results_are_compact_and_decode_redirects():
    parser = browser._SearchParser()
    parser.feed('''<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fnews">Example</a>
                   <div class="result__snippet">A <b>useful</b> result.</div>''')
    assert parser.results == [{"title": "Example", "url": "https://example.com/news",
                               "snippet": "A useful result."}]


def test_web_fetch_rejects_local_network_targets():
    for url in ("http://localhost:8000", "http://127.0.0.1", "http://169.254.169.254"):
        with pytest.raises(ToolError, match="local network|private or local"):
            browser._public_url(url)


def test_network_activity_labels_show_exact_addresses(box):
    assert registry.describe("web_fetch", {"url": "https://example.test/article"}, box) \
        == "https://example.test/article"
    assert registry.describe("browser_inspect", {"url": "https://example.test/app"}, box) \
        == "https://example.test/app"
    assert registry.describe("http_request", {
        "method": "post", "url": "https://api.example.test/items"}, box) \
        == "POST https://api.example.test/items"
    assert registry.describe("run_command", {"command": "pytest -q"}, box) == "pytest -q"
