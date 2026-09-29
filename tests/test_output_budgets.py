"""Tool output cannot bypass context budgets, even through parallelism or paging."""
import asyncio
import re

import httpx
import pytest

from eirene.core import agent as agent_mod, artifacts
from eirene.core.agent import ToolFinished
from eirene.core.tool_memory import compact_output
from eirene.providers.base import Done, TextDelta, ToolCall
from eirene.providers.local_profile import LocalProfile
from eirene.tools import browser, files, registry, shell
from test_agent import Script, build, drive


@pytest.mark.parametrize("limit", [0, 1, 30, 128, 256, 1024])
@pytest.mark.parametrize("prefix_only", [False, True])
def test_preview_never_exceeds_allowance(limit, prefix_only):
    result = compact_output("begin\n" + "x" * 10000 + "\nend", limit, "a" * 32,
                            prefix_only=prefix_only)
    assert len(result) <= limit
    if limit >= 256:
        assert "read_output" in result
        assert "partial output" in result
        assert result.startswith("begin")
        if not prefix_only:
            assert "end" in result


@pytest.mark.parametrize("name,args", [
    ("run_command", {"command": "echo evidence"}),
    ("list_dir", {"path": "."}),
    ("glob", {"pattern": "*.py"}),
    ("search_text", {"pattern": "pattern"}),
    ("web_fetch", {"url": "https://example.com"}),
    ("read_output", {"artifact_id": "a" * 32}),
])
async def test_every_tool_uses_local_budget(workdir, monkeypatch, name, args):
    provider = Script([ToolCall("one", name, args), Done("tool_use")],
                      [TextDelta("done"), Done("stop")])
    provider.profile = LocalProfile("compact", 3, 16, 8, 0)
    limits = []
    evidence = "FIRST diagnostic\n" + "x" * 100000 + "\nFINAL diagnostic"

    async def execute(*unused, max_bytes, **kwargs):
        limits.append(max_bytes)
        return evidence

    monkeypatch.setattr(agent_mod.tools, "execute", execute)
    runner = build(workdir, provider, isolate_network=False)
    events = await drive(runner)
    result = next(e for e in events if isinstance(e, ToolFinished))
    assert 0 < limits[0] <= 2048
    assert len(result.result) <= limits[0]
    assert artifacts.read(result.artifact_id, limit=200000) == evidence
    assert "read_output" in result.result
    assert result.result.startswith("FIRST diagnostic")
    if name not in {"read_output"}:
        assert "FINAL diagnostic" in result.result


async def test_parallel_reads_share_one_context_allowance(workdir, monkeypatch):
    provider = Script([ToolCall(str(i), "list_dir", {"path": str(i)}) for i in range(8)],
                      [TextDelta("done"), Done("stop")])
    provider.profile = LocalProfile("compact", 3, 16, 8, 0)
    observed = []

    async def execute(*unused, max_bytes, **kwargs):
        observed.append(max_bytes)
        await asyncio.sleep(0)
        return "entry\n" * 2000

    monkeypatch.setattr(agent_mod.tools, "execute", execute)
    runner = build(workdir, provider)
    # Force a small total remaining allowance to exercise simultaneous readers.
    monkeypatch.setattr(runner, "context_size", lambda: 1800)
    total = await runner._tool_output_limit()
    events = [e async for e in runner._dispatch(provider.turns[0])]
    results = [e.result for e in events if isinstance(e, ToolFinished)]
    assert len(results) == 8
    assert sum(map(len, results)) <= total
    assert max(observed) <= total // 8


async def test_artifact_pages_preserve_unicode_and_exact_offsets(box):
    original = "α🌍\n" * 1000
    writer = artifacts.Writer()
    writer.feed(original)
    writer.close()
    offset, bodies = 0, []
    while True:
        page = await registry.execute("read_output", {
            "artifact_id": writer.id, "offset": offset, "limit": 17}, box, max_bytes=512)
        assert len(page) <= 512
        assert "�" not in page
        lines = page.split("\n", 1)
        body, footer = lines[1].rsplit("\n", 1)
        bodies.append(body)
        end = int(re.search(r"bytes \d+-(\d+)", lines[0]).group(1))
        assert end > offset
        offset = end
        if "(end of output)" == footer:
            break
        assert f"next_offset={offset}" in footer
    assert "".join(bodies) == original


async def test_direct_shell_call_uses_workload_deadline(workdir, python_command, monkeypatch):
    monkeypatch.setattr(shell, "command_timeout", lambda command: 0.05)
    result = await shell.run(python_command("import time; time.sleep(10)"), workdir, stall=0)
    assert result.timed_out
    assert result.duration < 5


def test_shell_capture_respects_small_and_oversized_requests():
    small = shell._Capture(256)
    small.feed(b"HEAD" + b"x" * 100000 + b"TAIL")
    assert len(small.head) + len(small.tail) <= 256
    assert small.text().startswith("HEAD") and small.text().endswith("TAIL")
    assert shell._Capture(10**9).limit <= shell.DEFAULT_MAX_BYTES


def test_directory_and_glob_counts_survive_bounded_selection(box, workdir, monkeypatch):
    monkeypatch.setattr(files, "MAX_LIST_ENTRIES", 3)
    for i in range(10):
        (workdir / f"{i}.txt").write_text("x")
    listing = files.list_dir(box)
    assert listing.startswith("0.txt")
    assert "7 more" in listing
    assert "7 more" in files.glob_files(box, "*.txt")


async def test_http_download_stops_at_byte_cap(monkeypatch):
    monkeypatch.setattr(browser, "MAX_DOWNLOAD_BYTES", 10000)

    class Endless(httpx.AsyncByteStream):
        closed = False
        chunks = 0

        async def __aiter__(self):
            while True:
                self.chunks += 1
                yield b"x" * 8192

        async def aclose(self):
            self.closed = True

    stream = Endless()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
    async with httpx.AsyncClient(transport=transport) as client:
        response = await browser._download(client, "GET", "https://example.com", timeout=1)
    assert len(response.content) == 10000
    assert stream.closed and stream.chunks == 2
    assert "partial content" in browser._download_note(response)


async def test_http_deadline_stops_slow_stream():
    class Slow(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            while True:
                await asyncio.sleep(0.04)
                yield b"x"

        async def aclose(self):
            self.closed = True

    stream = Slow()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(browser.ToolError, match="timed out"):
            await browser._download(client, "GET", "https://example.com", timeout=0.1)
    assert stream.closed


async def test_redirects_close_intermediate_bodies_without_reading():
    class Unreadable(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            raise AssertionError("redirect body must not be read")
            yield b""

        async def aclose(self):
            self.closed = True

    stream = Unreadable()

    def respond(request):
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/end"}, stream=stream)
        return httpx.Response(200, content=b"final")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), follow_redirects=True) as client:
        response = await browser._download(client, "GET", "https://example.com/start", timeout=1)
    assert stream.closed
    assert response.text == "final"
    assert response.url.path == "/end"


async def test_cloud_output_allowance_tracks_configured_context(workdir):
    runner = build(workdir, Script([TextDelta("done")]),
                   model_context_limits={"test-model": 16000}, max_tokens=1024)
    roomy = await runner._tool_output_limit()
    runner.session.add_user("history " * 6500)
    tight = await runner._tool_output_limit()
    assert 0 < roomy <= 12000
    assert tight < roomy


def test_clipped_search_does_not_claim_complete_absence(box, workdir, monkeypatch):
    monkeypatch.setattr(files, "MAX_READ_BYTES", 32)
    (workdir / "long.txt").write_text("x" * 200 + "NEEDLE\n")
    result = files.search_text(box, "NEEDLE")
    assert "search is partial" in result
    assert "no matches in inspected text" in result


async def test_cli_owner_is_never_offered_native_tools(workdir):
    provider = Script([TextDelta("done"), Done("stop")])
    provider.owns_context = True
    # Even an adapter advertising tool support must not get Eirene's schemas.
    provider.supports_tools = True
    runner = build(workdir, provider)
    await drive(runner)
    assert provider.tools_seen == [None]
    assert "Set timeout=30" not in provider.systems[0]


def test_compact_model_retains_host_shell_and_output_instructions():
    profile = LocalProfile("compact", 3, 16, 8, 0)
    prompt = profile.system("Sandbox: /workspace\nOS: Windows | Shell: cmd\nMode is auto.")
    assert "OS: Windows | Shell: cmd" in prompt
    assert "powershell=true" in prompt
    assert "timeout: 30" in prompt
    assert "next_offset as offset" in prompt


async def test_command_stream_preserves_unicode_across_chunk_boundaries():
    from types import SimpleNamespace
    original = "start 🌍 α end\n"
    chunks = iter(bytes([value]) for value in original.encode())

    async def read(size):
        return next(chunks, b"")

    async def wait():
        return 0

    process = SimpleNamespace(stdout=SimpleNamespace(read=read), wait=wait)
    received = []
    capture = shell._Capture(1024)
    await shell._pump(process, capture, received.append)
    assert "".join(received) == original
    assert capture.text() == original
