"""Bounded Chromium and HTTP inspection tools."""

from __future__ import annotations

import asyncio
import html
import ipaddress
import json
import os
import re
import shutil
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import httpx

try:  # Optional at import time so source checkouts can still show diagnostics.
    import websockets
except ImportError:  # pragma: no cover - dependency is installed in builds
    websockets = None

from ..core.errors import ToolError
from ..core.subprocesses import executable_argv
from .sandbox import Sandbox

MAX_DOM = 120_000
MAX_RESPONSE = 120_000
MAX_SEARCH = 6_000
MAX_PAGE_TEXT = 16_000
MAX_BROWSER_RESULT = 32_000

# Chromium uses different executable names and default install locations on each
# desktop OS.  PATH remains the preferred, portable mechanism; the explicit
# locations cover normal Chrome/Chromium installs whose launchers are not added
# to PATH (notably Windows and macOS).
EXECUTABLE_NAMES = (
    "chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
    "chrome", "chrome.exe", "msedge", "msedge.exe",
)


def executable() -> str:
    override = os.environ.get("EIRENE_CHROMIUM_PATH", "").strip()
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file():
            return str(candidate)
        raise ToolError(f"EIRENE_CHROMIUM_PATH does not point to a file: {candidate}")
    for name in EXECUTABLE_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for candidate in _installed_browsers():
        if candidate.is_file():
            return str(candidate)
    raise ToolError("Chromium is not installed or not on PATH")


def _installed_browsers() -> list[Path]:
    """Normal browser locations not reliably exposed through PATH."""
    if sys.platform == "darwin":
        return [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            Path.home() / "Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    if sys.platform.startswith("win"):
        roots = [os.environ.get(name, "") for name in
                 ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        relative = (
            "Google/Chrome/Application/chrome.exe",
            "Chromium/Application/chrome.exe",
            "Microsoft/Edge/Application/msedge.exe",
        )
        return [Path(root) / path for root in roots if root for path in relative]
    return [
        Path("/usr/bin/chromium"), Path("/usr/bin/chromium-browser"),
        Path("/usr/bin/google-chrome"), Path("/opt/google/chrome/chrome"),
        Path("/snap/bin/chromium"),
    ]


def _url(raw: str) -> str:
    value = str(raw or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ToolError("URL must be an absolute http:// or https:// address")
    if parsed.username or parsed.password:
        raise ToolError("credentials in browser URLs are not allowed")
    return value


async def inspect(url: str, *, timeout: float = 30) -> str:
    """Render a page in Chromium and return its post-JavaScript DOM."""
    target = _url(url)
    with tempfile.TemporaryDirectory(prefix="eirene-chromium-") as profile:
        argv = _argv(profile, timeout) + ["--dump-dom", target]
        stdout, stderr, code = await _run(argv, timeout + 5)
    if code:
        raise ToolError(_failure(stderr, code))
    text = stdout.decode("utf-8", "replace")
    return _bounded(text, MAX_DOM)


async def screenshot(box: Sandbox, url: str, path: str, *, width: int = 1440,
                     height: int = 900, timeout: float = 30) -> str:
    """Render a page and save a PNG inside the working directory."""
    target = _url(url)
    destination = box.check_write_target(path)
    if destination.suffix.lower() != ".png":
        raise ToolError("browser screenshots must use a .png path")
    width = max(320, min(int(width), 3840))
    height = max(240, min(int(height), 2160))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="eirene-chromium-") as profile:
        argv = _argv(profile, timeout) + [f"--window-size={width},{height}",
                f"--screenshot={destination}", target]
        _, stderr, code = await _run(argv, timeout + 5)
    if code or not destination.is_file():
        raise ToolError(_failure(stderr, code))
    return (f"saved {box.relative(destination)} ({width}x{height}); "
            "use read_image to inspect it")


async def interact(url: str, actions: list[dict], *, timeout: float = 30) -> str:
    """Run a bounded batch of DOM interactions through Chromium DevTools.

    One ephemeral browser handles the whole batch, which is substantially cheaper
    than launching a browser (or an MCP round trip) for every click and field.
    """
    target = _url(url)
    if not isinstance(actions, list) or not actions:
        raise ToolError("browser actions must be a non-empty array")
    if len(actions) > 25:
        raise ToolError("at most 25 browser actions are allowed per call")
    if websockets is None:
        raise ToolError("interactive Chromium needs the 'websockets' package")

    with tempfile.TemporaryDirectory(prefix="eirene-chromium-") as profile:
        argv = [part for part in _argv(profile, timeout)
                if not part.startswith("--virtual-time-budget=")]
        # A zero port lets Chromium choose a free loopback port and publish it in
        # DevToolsActivePort, avoiding races and platform-specific socket passing.
        argv += ["--remote-debugging-port=0", "about:blank"]
        process = await asyncio.create_subprocess_exec(
            *executable_argv(argv[0], *argv[1:]), stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE)
        try:
            endpoint = await _devtools_endpoint(Path(profile), process, timeout)
            async with websockets.connect(endpoint, open_timeout=timeout,
                                          max_size=2_000_000) as socket:
                cdp = _CDP(socket)
                created = await cdp.call("Target.createTarget", {"url": target})
                attached = await cdp.call("Target.attachToTarget", {
                    "targetId": created["targetId"], "flatten": True})
                session = attached["sessionId"]
                await cdp.call("Page.enable", session=session)
                await cdp.call("Runtime.enable", session=session)
                await _ready(cdp, session, timeout)
                results = []
                for index, action in enumerate(actions, 1):
                    results.append(await _browser_action(cdp, session, action, index))
                return _bounded("\n".join(results), MAX_BROWSER_RESULT)
        except asyncio.TimeoutError as exc:
            raise ToolError("interactive Chromium timed out") from exc
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()


class _CDP:
    def __init__(self, socket):
        self.socket = socket
        self.sequence = 0

    async def call(self, method: str, params: dict | None = None, *, session: str = ""):
        self.sequence += 1
        wanted = self.sequence
        message = {"id": wanted, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        await self.socket.send(json.dumps(message))
        while True:
            reply = json.loads(await self.socket.recv())
            if reply.get("id") != wanted:
                continue
            if reply.get("error"):
                raise ToolError(f"Chromium {method} failed: {reply['error'].get('message', 'error')}")
            return reply.get("result", {})


async def _devtools_endpoint(profile: Path, process, timeout: float) -> str:
    marker = profile / "DevToolsActivePort"
    deadline = asyncio.get_running_loop().time() + min(timeout, 30)
    while asyncio.get_running_loop().time() < deadline:
        if process.returncode is not None:
            detail = (await process.stderr.read()).decode("utf-8", "replace")[-1000:]
            raise ToolError(f"Chromium exited {process.returncode}: {detail.strip()}")
        try:
            lines = marker.read_text(encoding="utf-8").splitlines()
            if len(lines) >= 2:
                return f"ws://127.0.0.1:{int(lines[0])}{lines[1]}"
        except (OSError, ValueError):
            pass
        await asyncio.sleep(0.05)
    raise asyncio.TimeoutError


async def _ready(cdp: _CDP, session: str, timeout: float) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        reply = await cdp.call("Runtime.evaluate", {
            "expression": "document.readyState", "returnByValue": True}, session=session)
        if reply.get("result", {}).get("value") in {"interactive", "complete"}:
            return
        await asyncio.sleep(0.1)
    raise asyncio.TimeoutError


async def _browser_action(cdp: _CDP, session: str, action: dict, index: int) -> str:
    if not isinstance(action, dict):
        raise ToolError(f"browser action {index} must be an object")
    kind = str(action.get("action") or "").strip().lower()
    if kind == "wait":
        milliseconds = max(0, min(int(action.get("milliseconds", 250)), 10_000))
        await asyncio.sleep(milliseconds / 1000)
        return f"{index}. waited {milliseconds}ms"
    if kind == "navigate":
        target = _url(str(action.get("url") or ""))
        await cdp.call("Page.navigate", {"url": target}, session=session)
        await _ready(cdp, session, 30)
        return f"{index}. navigated {target}"
    if kind in {"click", "type"}:
        selector = str(action.get("selector") or "").strip()
        if not selector:
            raise ToolError(f"browser action {index} needs a selector")
        encoded = json.dumps(selector)
        if kind == "click":
            expression = (f"(()=>{{const e=document.querySelector({encoded});"
                          "if(!e)throw new Error('selector not found');e.click();return true}})()")
        else:
            value = json.dumps(str(action.get("text") or ""))
            expression = (f"(()=>{{const e=document.querySelector({encoded});"
                          "if(!e)throw new Error('selector not found');e.focus();"
                          f"e.value={value};e.dispatchEvent(new Event('input',{{bubbles:true}}));"
                          "e.dispatchEvent(new Event('change',{bubbles:true}));return true}})()")
        await _evaluate(cdp, session, expression)
        return f"{index}. {kind} {selector}"
    if kind in {"evaluate", "dom", "text"}:
        expression = str(action.get("expression") or "") if kind == "evaluate" else (
            "document.documentElement.outerHTML" if kind == "dom" else
            "document.body ? document.body.innerText : ''")
        value = await _evaluate(cdp, session, expression)
        rendered = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
        return f"{index}. {kind}\n{_bounded(rendered, 16_000)}"
    raise ToolError(f"unsupported browser action '{kind}'")


async def _evaluate(cdp: _CDP, session: str, expression: str):
    reply = await cdp.call("Runtime.evaluate", {"expression": expression,
                           "awaitPromise": True, "returnByValue": True}, session=session)
    if reply.get("exceptionDetails"):
        detail = reply["exceptionDetails"].get("text", "JavaScript failed")
        raise ToolError(f"browser JavaScript failed: {detail}")
    return reply.get("result", {}).get("value")


async def request(method: str, url: str, *, headers: dict | None = None,
                  body: str = "", timeout: float = 30) -> str:
    """Send an explicit bounded HTTP request."""
    target = _url(url)
    verb = str(method or "GET").upper()
    if verb not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}:
        raise ToolError(f"unsupported HTTP method {verb}")
    clean_headers = {str(k): str(v) for k, v in (headers or {}).items()}
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            response = await client.request(verb, target, headers=clean_headers,
                                            content=body.encode() if body else None)
    except httpx.HTTPError as exc:
        raise ToolError(f"HTTP request failed: {exc}") from exc
    meta = {"status": response.status_code, "url": str(response.url),
            "headers": dict(response.headers)}
    content = response.text
    return json.dumps(meta, indent=2) + "\n\n" + _bounded(content, MAX_RESPONSE)


async def search(query: str, *, limit: int = 5, timeout: float = 15) -> str:
    """Return compact web results without launching a browser."""
    wanted = str(query or "").strip()
    if not wanted:
        raise ToolError("search query is empty")
    limit = max(1, min(int(limit), 8))
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(wanted)}"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; Eirene/1.0)"}
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ToolError(f"web search failed: {exc}") from exc
    parser = _SearchParser()
    parser.feed(response.text)
    results = parser.results[:limit]
    if not results:
        raise ToolError("web search returned no readable results")
    lines = [f"Search results for: {wanted}"]
    for index, item in enumerate(results, 1):
        lines.extend((f"{index}. {item['title']}", item["url"], item["snippet"]))
    return _bounded("\n".join(lines), MAX_SEARCH)


async def fetch_text(url: str, *, timeout: float = 20) -> str:
    """Download one public page and reduce HTML to bounded readable text."""
    target = _public_url(url)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; Eirene/1.0)"}
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
            for _ in range(4):
                response = await client.get(target, headers=headers)
                if response.is_redirect:
                    target = _public_url(urljoin(target, response.headers.get("location", "")))
                    continue
                response.raise_for_status()
                break
            else:
                raise ToolError("page redirected too many times")
    except httpx.HTTPError as exc:
        raise ToolError(f"page fetch failed: {exc}") from exc
    content_type = response.headers.get("content-type", "").lower()
    if "html" not in content_type and not content_type.startswith("text/"):
        raise ToolError(f"page is not readable text ({content_type or 'unknown type'})")
    parser = _TextParser()
    parser.feed(response.text)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(parser.parts)).strip()
    if not text:
        raise ToolError("page contained no readable text")
    return f"Source: {response.url}\n\n{_bounded(text, MAX_PAGE_TEXT)}"


class _SearchParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._field = ""
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        classes = values.get("class", "").split()
        if tag == "a" and "result__a" in classes:
            self._field, self._href, self._text = "title", values.get("href", ""), []
        elif "result__snippet" in classes:
            self._field, self._text = "snippet", []

    def handle_data(self, data: str) -> None:
        if self._field:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._field == "title" and tag == "a":
            self.results.append({"title": _clean(" ".join(self._text)),
                                 "url": _result_url(self._href), "snippet": ""})
            self._field = ""
        elif self._field == "snippet" and tag in {"a", "div"}:
            if self.results:
                self.results[-1]["snippet"] = _clean(" ".join(self._text))
            self._field = ""


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "svg", "noscript"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg", "noscript"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        value = _clean(data)
        if value and not self._skip:
            self.parts.append(value)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _result_url(raw: str) -> str:
    value = urljoin("https://duckduckgo.com", raw)
    query = parse_qs(urlparse(value).query)
    return unquote(query.get("uddg", [value])[0])


def _public_url(raw: str) -> str:
    value = _url(raw)
    host = (urlparse(value).hostname or "").lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        raise ToolError("local network addresses are not allowed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return value
    if not address.is_global:
        raise ToolError("private or local network addresses are not allowed")
    return value


def _argv(profile: str, timeout: float) -> list[str]:
    budget = max(1, min(int(timeout * 1000), 120_000))
    return [executable(), "--headless=new", "--disable-gpu", "--disable-dev-shm-usage",
            "--no-first-run", "--no-default-browser-check", "--hide-scrollbars",
            "--disable-background-networking", "--disable-component-update",
            "--disable-default-apps", "--disable-extensions", "--disable-sync",
            "--metrics-recording-only", "--mute-audio", "--renderer-process-limit=2",
            f"--user-data-dir={profile}", f"--virtual-time-budget={budget}"]


async def _run(argv: list[str], timeout: float) -> tuple[bytes, bytes, int]:
    try:
        process = await asyncio.create_subprocess_exec(
            *executable_argv(argv[0], *argv[1:]), stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise ToolError("Chromium timed out and was stopped") from exc
    except OSError as exc:
        raise ToolError(f"could not start Chromium: {exc}") from exc
    return stdout, stderr, int(process.returncode or 0)


def _failure(stderr: bytes, code: int) -> str:
    detail = stderr.decode("utf-8", "replace").strip()[-1000:]
    return f"Chromium exited {code}" + (f": {detail}" if detail else "")


def _bounded(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… truncated {len(text) - limit} characters"
